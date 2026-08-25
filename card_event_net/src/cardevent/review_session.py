from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .annotation import (
    EVENT_TYPES,
    AnnotationError,
    VideoAnnotation,
    annotation_path_for_video,
    load_annotation,
)
from .video import VideoError, resolve_video_path

REVIEW_QUEUE_FORMAT = "cardevent-review-queue-v1"
REVIEW_OUTCOMES = frozenset(
    {
        "confirmed_positive",
        "confirmed_hard_negative",
        "annotation_timestamp_corrected",
        "ignore",
        "unreviewed",
    }
)
REVIEW_STATUSES = frozenset({"unreviewed", "reviewed"})
POSITIVE_TARGETS = frozenset({"new_event", "existing_annotation"})


class ReviewSessionError(RuntimeError):
    """Raised when a review session cannot be loaded or changed safely."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReviewSessionError(f"Could not read review queue {path}: {exc}") from exc
    return digest.hexdigest()


def _finite_non_negative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewSessionError(f"{name} must be a number.")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ReviewSessionError(f"{name} must be finite and non-negative.")
    return result


def _optional_time(item: Mapping[str, Any], key: str) -> None:
    value = item.get(key)
    if value is not None:
        _finite_non_negative(value, key)


def _validate_item(item: Mapping[str, Any], *, output: bool = False) -> None:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise ReviewSessionError("Each review item needs a non-empty id.")
    video = item.get("video")
    if not isinstance(video, str) or not video or Path(video).name != video:
        raise ReviewSessionError(f"Review item {item_id} needs a simple video name.")
    if not isinstance(item.get("status"), str) or item["status"] not in REVIEW_STATUSES:
        raise ReviewSessionError("Review item status must be unreviewed or reviewed.")
    outcome = item.get("outcome")
    if outcome not in REVIEW_OUTCOMES:
        raise ReviewSessionError(f"Review item outcome is invalid: {item_id}")
    if item["status"] == "unreviewed" and outcome != "unreviewed":
        raise ReviewSessionError(f"An unreviewed item has an outcome: {item_id}")
    if item["status"] == "reviewed" and outcome == "unreviewed":
        raise ReviewSessionError(f"Reviewed item has no outcome: {item_id}")
    _finite_non_negative(item.get("timestamp_s"), "review timestamp")

    event_type = item.get("event_type")
    if event_type is not None and event_type not in EVENT_TYPES:
        raise ReviewSessionError(f"Review item event_type is invalid: {item_id}")
    target = item.get("positive_target")
    if target is not None and target not in POSITIVE_TARGETS:
        raise ReviewSessionError(f"Review item positive_target is invalid: {item_id}")
    _optional_time(item, "source_annotation_time_s")
    _optional_time(item, "original_timestamp_s")

    notes = item.get("review_notes")
    if notes is not None and not isinstance(notes, str):
        raise ReviewSessionError(f"Review item review_notes must be a string or null: {item_id}")
    reviewed_at = item.get("reviewed_at")
    if reviewed_at is not None and (not isinstance(reviewed_at, str) or not reviewed_at):
        raise ReviewSessionError(
            f"Review item reviewed_at must be a non-empty string or null: {item_id}"
        )

    if target is not None and outcome != "confirmed_positive":
        raise ReviewSessionError(f"positive_target requires a confirmed positive: {item_id}")
    if target == "existing_annotation" and item.get("source_annotation_time_s") is None:
        raise ReviewSessionError(
            f"Existing positive needs a source annotation reference: {item_id}"
        )
    if output and item["status"] == "reviewed" and outcome == "confirmed_positive":
        if target is None:
            raise ReviewSessionError(
                f"Confirmed positive needs an explicit positive_target: {item_id}"
            )
        if target == "new_event" and event_type is None:
            raise ReviewSessionError(f"New positive needs an event_type: {item_id}")
    if output and item["status"] == "reviewed":
        if outcome in {"ignore", "confirmed_hard_negative"} and (
            event_type is not None
            or target is not None
            or item.get("source_annotation_time_s") is not None
        ):
            raise ReviewSessionError(
                f"Non-positive decision has mutable positive fields: {item_id}"
            )
        if (
            outcome == "annotation_timestamp_corrected"
            and item.get("source_annotation_time_s") is None
        ):
            raise ReviewSessionError(
                f"Timestamp correction needs a source annotation reference: {item_id}"
            )
    if output and item["status"] == "reviewed" and reviewed_at is None:
        raise ReviewSessionError(f"Reviewed item needs reviewed_at: {item_id}")


def validate_review_queue(payload: Mapping[str, Any], *, output: bool = False) -> None:
    if payload.get("format") != REVIEW_QUEUE_FORMAT:
        raise ReviewSessionError("Unsupported review queue format.")
    items = payload.get("items")
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise ReviewSessionError("Review queue items must be a list of mappings.")
    identities: set[str] = set()
    for item in items:
        _validate_item(item, output=output)
        item_id = str(item["id"])
        if item_id in identities:
            raise ReviewSessionError(f"Review queue contains duplicate item id: {item_id}")
        identities.add(item_id)

    if output:
        for key in (
            "source_queue",
            "source_queue_sha256",
            "reviewer",
            "review_started_at",
            "review_updated_at",
        ):
            value = payload.get(key)
            if not isinstance(value, str) or not value:
                raise ReviewSessionError(f"Reviewed queue needs a non-empty {key}.")


def load_review_queue(path: str | Path, *, output: bool = False) -> dict[str, Any]:
    queue_path = Path(path)
    try:
        payload = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewSessionError(f"Could not read review queue {queue_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewSessionError("Review queue must contain a JSON object.")
    validate_review_queue(payload, output=output)
    return payload


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        with contextlib.suppress(UnboundLocalError, OSError):
            temporary.unlink(missing_ok=True)
        raise ReviewSessionError(f"Could not save reviewed queue {path}: {exc}") from exc


def _copy_decision_fields(item: dict[str, Any]) -> None:
    item.setdefault("original_timestamp_s", item["timestamp_s"])
    item.setdefault("positive_target", None)
    item.setdefault("source_annotation_time_s", None)
    item.setdefault("reviewed_at", None)
    item.setdefault("review_notes", None)


def _immutable_item(item: Mapping[str, Any]) -> dict[str, Any]:
    mutable = {
        "status",
        "outcome",
        "event_type",
        "timestamp_s",
        "positive_target",
        "source_annotation_time_s",
        "original_timestamp_s",
        "reviewed_at",
        "review_notes",
    }
    return {key: value for key, value in item.items() if key not in mutable}


def resolve_video_paths(
    videos_dir: str | Path, video_names: list[str] | tuple[str, ...]
) -> dict[str, Path]:
    directory = Path(videos_dir)
    if not directory.is_dir():
        raise ReviewSessionError(f"Video directory does not exist: {directory}")
    resolved: dict[str, Path] = {}
    for video_name in dict.fromkeys(video_names):
        try:
            resolved[video_name] = resolve_video_path(directory, video_name)
        except VideoError as exc:
            raise ReviewSessionError(str(exc)) from exc
    return resolved


@dataclass(frozen=True, slots=True)
class ReviewSelection:
    selected_count: int
    reviewed_count: int
    remaining_count: int

    def to_mapping(self) -> dict[str, int]:
        return {
            "selected": self.selected_count,
            "reviewed": self.reviewed_count,
            "remaining": self.remaining_count,
        }


@dataclass(slots=True)
class ReviewSession:
    queue_path: Path
    output_path: Path
    videos_dir: Path
    annotations_dir: Path
    reviewer: str
    payload: dict[str, Any]
    selected_indices: tuple[int, ...]
    current_selection: int | None = None
    current_frame_index: int | None = None
    selected_event_type: str = "card_played"
    video_paths: dict[str, Path] | None = None
    selected_annotation_time_s: float | None = None
    annotation_targets_by_video: dict[str, tuple[dict[str, Any], ...]] | None = None

    @classmethod
    def open(
        cls,
        queue_path: str | Path,
        output_path: str | Path,
        *,
        videos_dir: str | Path,
        annotations_dir: str | Path,
        reviewer: str,
        video: str | None = None,
        category: str | None = None,
        include_reviewed: bool = False,
        start_item: str | None = None,
    ) -> "ReviewSession":
        if not reviewer or not reviewer.strip():
            raise ReviewSessionError("A non-empty reviewer name is required.")
        source = Path(queue_path)
        destination = Path(output_path)
        if source.resolve() == destination.resolve():
            raise ReviewSessionError("The reviewed queue output must differ from the source queue.")
        source_hash = _sha256(source)
        source_payload = load_review_queue(source)

        if destination.exists():
            payload = load_review_queue(destination, output=True)
            if payload.get("source_queue_sha256") != source_hash:
                raise ReviewSessionError(
                    "The reviewed queue source checksum does not match --queue."
                )
            if payload.get("reviewer") != reviewer:
                raise ReviewSessionError("The reviewed queue reviewer does not match --reviewer.")
            source_ids = [item["id"] for item in source_payload["items"]]
            output_ids = [item["id"] for item in payload["items"]]
            if source_ids != output_ids:
                raise ReviewSessionError("The reviewed queue item identities do not match --queue.")
            for source_item, output_item in zip(
                source_payload["items"], payload["items"], strict=True
            ):
                if _immutable_item(source_item) != _immutable_item(output_item):
                    raise ReviewSessionError(
                        f"Immutable review item fields do not match --queue: {source_item['id']}"
                    )
        else:
            if source_payload.get("reviewer") not in (None, reviewer):
                raise ReviewSessionError("The source queue reviewer does not match --reviewer.")
            payload = copy.deepcopy(source_payload)
            payload.update(
                {
                    "source_queue": str(source),
                    "source_queue_sha256": source_hash,
                    "reviewer": reviewer,
                    "review_started_at": payload.get("review_started_at") or _now(),
                    "review_updated_at": _now(),
                }
            )
            for item in payload["items"]:
                _copy_decision_fields(item)
            validate_review_queue(payload, output=True)
            _atomic_write(destination, payload)

        for item in payload["items"]:
            _copy_decision_fields(item)
        validate_review_queue(payload, output=True)
        selected_indices = tuple(
            index
            for index, item in enumerate(payload["items"])
            if (include_reviewed or item["status"] == "unreviewed")
            and (video is None or cls._matches_video_filter(item["video"], video))
            and (category is None or item.get("category") == category)
        )
        current_selection: int | None = None
        if selected_indices:
            current_selection = next(
                (
                    position
                    for position, index in enumerate(selected_indices)
                    if payload["items"][index]["status"] == "unreviewed"
                ),
                0,
            )
        if start_item is not None:
            try:
                current_selection = selected_indices.index(
                    next(
                        index
                        for index, item in enumerate(payload["items"])
                        if item["id"] == start_item
                    )
                )
            except (StopIteration, ValueError) as exc:
                raise ReviewSessionError(
                    f"Start item is not in the selected queue: {start_item}"
                ) from exc

        paths = resolve_video_paths(
            videos_dir,
            [payload["items"][index]["video"] for index in selected_indices],
        )
        session = cls(
            queue_path=source,
            output_path=destination,
            videos_dir=Path(videos_dir),
            annotations_dir=Path(annotations_dir),
            reviewer=reviewer,
            payload=payload,
            selected_indices=selected_indices,
            current_selection=current_selection,
            video_paths=paths,
        )
        if current_selection is not None:
            session._set_current_type()
            session._reset_annotation_target()
        return session

    @staticmethod
    def _matches_video_filter(item_video: str, selected_video: str) -> bool:
        return (
            item_video == selected_video
            or Path(item_video).stem.casefold() == Path(selected_video).stem.casefold()
        )

    @property
    def items(self) -> list[dict[str, Any]]:
        return self.payload["items"]

    @property
    def current_item(self) -> dict[str, Any] | None:
        if self.current_selection is None:
            return None
        return self.items[self.selected_indices[self.current_selection]]

    @property
    def selection(self) -> ReviewSelection:
        selected = [self.items[index] for index in self.selected_indices]
        reviewed = sum(item["status"] == "reviewed" for item in selected)
        return ReviewSelection(
            selected_count=len(selected),
            reviewed_count=reviewed,
            remaining_count=len(selected) - reviewed,
        )

    def summary(self) -> dict[str, int]:
        return self.selection.to_mapping()

    def video_path_for(self, item: Mapping[str, Any] | None = None) -> Path:
        current = self.current_item if item is None else item
        if current is None:
            raise ReviewSessionError("The review selection is empty.")
        if self.video_paths is None or current["video"] not in self.video_paths:
            raise ReviewSessionError(f"Video is not resolved: {current['video']}")
        return self.video_paths[current["video"]]

    def source_annotation_for(self, item: Mapping[str, Any] | None = None) -> VideoAnnotation:
        current = self.current_item if item is None else item
        if current is None:
            raise ReviewSessionError("The review selection is empty.")
        annotation_path = annotation_path_for_video(
            self.video_path_for(current), annotations_dir=self.annotations_dir
        )
        try:
            return load_annotation(annotation_path)
        except AnnotationError as exc:
            raise ReviewSessionError(
                f"Could not load source annotation {annotation_path}: {exc}"
            ) from exc

    def frame_index_for(self, fps: float, item: Mapping[str, Any] | None = None) -> int:
        current = self.current_item if item is None else item
        if current is None:
            raise ReviewSessionError("The review selection is empty.")
        if not math.isfinite(fps) or fps <= 0.0:
            raise ReviewSessionError("Video fps must be finite and positive.")
        return max(0, int(round(float(current["timestamp_s"]) * fps)))

    def _set_current_type(self) -> None:
        item = self.current_item
        self.selected_event_type = (
            item.get("event_type")
            if item and item.get("event_type") in EVENT_TYPES
            else "card_played"
        )

    def probability_stream_for(
        self, item: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any] | None:
        """Return the optional video-level timeline for a queue item."""
        current = self.current_item if item is None else item
        streams = self.payload.get("probability_streams")
        if current is None or not isinstance(streams, Mapping):
            return None
        stream = streams.get(current.get("video"))
        return stream if isinstance(stream, Mapping) else None

    def annotation_targets(
        self, item: Mapping[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return ordered source annotations, with old-queue fallbacks."""
        current = self.current_item if item is None else item
        if current is None:
            return ()
        stream = self.probability_stream_for(current)
        if stream is not None:
            events = stream.get("ground_truth_events")
            if isinstance(events, list):
                valid = tuple(
                    sorted(
                        (
                            {"time_s": float(event["time_s"]), "type": str(event["type"])}
                            for event in events
                            if isinstance(event, Mapping)
                            and isinstance(event.get("time_s"), (int, float))
                            and not isinstance(event.get("time_s"), bool)
                            and event.get("type") in EVENT_TYPES
                        ),
                        key=lambda event: float(event["time_s"]),
                    )
                )
                if valid:
                    return valid

        video_name = str(current["video"])
        if self.annotation_targets_by_video is None:
            self.annotation_targets_by_video = {}
        if video_name not in self.annotation_targets_by_video:
            try:
                annotation = self.source_annotation_for(current)
            except ReviewSessionError:
                source_targets: tuple[dict[str, Any], ...] = ()
            else:
                source_targets = tuple(
                    sorted(
                        (
                            {
                                "time_s": float(event.time_s),
                                "type": event.type,
                            }
                            for event in annotation.events
                            if event.confidence in {None, "confirmed"}
                        ),
                        key=lambda event: float(event["time_s"]),
                    )
                )
            self.annotation_targets_by_video[video_name] = source_targets
        cached = self.annotation_targets_by_video[video_name]
        if cached:
            return cached

        nearest = current.get("nearest_annotation")
        if isinstance(nearest, Mapping):
            time_s = nearest.get("time_s")
            event_type = nearest.get("type")
            if (
                isinstance(time_s, (int, float))
                and not isinstance(time_s, bool)
                and event_type in EVENT_TYPES
            ):
                return ({"time_s": float(time_s), "type": str(event_type)},)
        return ()

    @property
    def selected_annotation_target(self) -> dict[str, Any] | None:
        targets = self.annotation_targets()
        if not targets:
            return None
        selected = self.selected_annotation_time_s
        if selected is None:
            nearest = self.current_item.get("nearest_annotation") if self.current_item else None
            if isinstance(nearest, Mapping):
                selected = nearest.get("time_s")
            if not isinstance(selected, (int, float)) or isinstance(selected, bool):
                return targets[0]
        return min(targets, key=lambda target: abs(float(target["time_s"]) - selected))

    def _reset_annotation_target(self) -> None:
        targets = self.annotation_targets()
        if not targets:
            self.selected_annotation_time_s = None
            return
        nearest = self.current_item.get("nearest_annotation") if self.current_item else None
        nearest_time = nearest.get("time_s") if isinstance(nearest, Mapping) else None
        selected = next(
            (
                target
                for target in targets
                if isinstance(nearest_time, (int, float))
                and not isinstance(nearest_time, bool)
                and abs(float(target["time_s"]) - float(nearest_time)) <= 1e-6
            ),
            targets[0],
        )
        self.selected_annotation_time_s = float(selected["time_s"])

    def set_annotation_target(self, time_s: float) -> dict[str, Any]:
        value = _finite_non_negative(time_s, "annotation target time")
        targets = self.annotation_targets()
        for target in targets:
            if abs(float(target["time_s"]) - value) <= 1e-6:
                self.selected_annotation_time_s = float(target["time_s"])
                return target
        raise ReviewSessionError("The annotation target is not in this video's source events.")

    def select_annotation_target(self, direction: int) -> dict[str, Any] | None:
        targets = self.annotation_targets()
        if not targets:
            self.selected_annotation_time_s = None
            return None
        current = self.selected_annotation_target
        index = next(
            (
                position
                for position, target in enumerate(targets)
                if current is not None
                and abs(float(target["time_s"]) - float(current["time_s"])) <= 1e-6
            ),
            0,
        )
        index = max(0, min(index + (1 if direction > 0 else -1), len(targets) - 1))
        self.selected_annotation_time_s = float(targets[index]["time_s"])
        return targets[index]

    def previous_annotation_target(self) -> dict[str, Any] | None:
        return self.select_annotation_target(-1)

    def next_annotation_target(self) -> dict[str, Any] | None:
        return self.select_annotation_target(1)

    def set_event_type(self, event_type: str) -> None:
        if event_type not in EVENT_TYPES:
            raise ReviewSessionError(f"Unknown event type: {event_type}")
        self.selected_event_type = event_type

    def _move_to_selection(self, position: int) -> dict[str, Any] | None:
        if not self.selected_indices:
            self.current_selection = None
            return None
        self.current_selection = max(0, min(position, len(self.selected_indices) - 1))
        self.current_frame_index = None
        self._set_current_type()
        self._reset_annotation_target()
        return self.current_item

    def next_item(self, *, unreviewed_only: bool = False) -> dict[str, Any] | None:
        if self.current_selection is None:
            return None
        for position in range(self.current_selection + 1, len(self.selected_indices)):
            item = self.items[self.selected_indices[position]]
            if not unreviewed_only or item["status"] == "unreviewed":
                return self._move_to_selection(position)
        return self.current_item

    def advance_after_decision(self) -> dict[str, Any] | None:
        """Move to the next remaining item, or finish the selected queue."""
        if self.current_selection is None:
            return None
        for position in range(self.current_selection + 1, len(self.selected_indices)):
            item = self.items[self.selected_indices[position]]
            if item["status"] == "unreviewed":
                return self._move_to_selection(position)
        self.current_selection = None
        self.current_frame_index = None
        return None

    def previous_item(self) -> dict[str, Any] | None:
        if self.current_selection is None:
            return None
        return self._move_to_selection(max(0, self.current_selection - 1))

    def _require_current(self) -> dict[str, Any]:
        item = self.current_item
        if item is None:
            raise ReviewSessionError("The review selection is empty.")
        return item

    def _check_revisit(self, item: Mapping[str, Any], confirm: bool) -> None:
        if item["status"] == "reviewed" and not confirm:
            raise ReviewSessionError("The item is already reviewed; confirmation is required.")

    def _require_note(self, item: Mapping[str, Any], note: str | None) -> str | None:
        selected_note = item.get("review_notes") if note is None else note
        if selected_note is not None and not isinstance(selected_note, str):
            raise ReviewSessionError("Review notes must be text.")
        selected_note = selected_note.strip() if selected_note else None
        if item.get("category") == "anomalous_state_change" and not selected_note:
            raise ReviewSessionError("An anomalous_state_change decision requires a review note.")
        return selected_note

    @staticmethod
    def _nearest(
        item: Mapping[str, Any], target: Mapping[str, Any] | None = None
    ) -> tuple[float, str]:
        nearest = item.get("nearest_annotation") if target is None else target
        if not isinstance(nearest, Mapping):
            raise ReviewSessionError("This decision needs exactly one nearest source annotation.")
        time_s = nearest.get("time_s")
        event_type = nearest.get("type")
        if (
            isinstance(time_s, bool)
            or not isinstance(time_s, (int, float))
            or event_type not in EVENT_TYPES
        ):
            raise ReviewSessionError(
                "This decision needs exactly one valid nearest source annotation."
            )
        return _finite_non_negative(time_s, "nearest annotation time"), str(event_type)

    def decide(
        self,
        outcome: str,
        *,
        current_time_s: float | None = None,
        event_type: str | None = None,
        positive_target: str | None = None,
        source_annotation_time_s: float | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        item = self._require_current()
        self._check_revisit(item, confirm)
        if outcome not in REVIEW_OUTCOMES - {"unreviewed"}:
            raise ReviewSessionError(f"Unsupported review decision: {outcome}")
        original_time = _finite_non_negative(
            item.get("original_timestamp_s", item["timestamp_s"]), "original timestamp"
        )
        timestamp = (
            original_time
            if current_time_s is None
            else _finite_non_negative(current_time_s, "current timestamp")
        )
        note_value = self._require_note(item, note)
        selected_target = self.selected_annotation_target
        if source_annotation_time_s is not None:
            source_time_value = _finite_non_negative(
                source_annotation_time_s, "source annotation time"
            )
            selected_target = next(
                (
                    target
                    for target in self.annotation_targets(item)
                    if abs(float(target["time_s"]) - source_time_value) <= 1e-6
                ),
                None,
            )
            if selected_target is None:
                raise ReviewSessionError(
                    "The source annotation time is not an available annotation target."
                )
        updates: dict[str, Any] = {
            "original_timestamp_s": original_time,
            "review_notes": note_value,
            "reviewed_at": _now(),
            "status": "reviewed",
            "outcome": outcome,
        }
        if outcome == "confirmed_positive":
            target = positive_target or "new_event"
            if target == "new_event":
                selected_type = event_type or self.selected_event_type
                if selected_type not in EVENT_TYPES:
                    raise ReviewSessionError(
                        "A new confirmed positive needs a selected event type."
                    )
                updates.update(
                    {
                        "timestamp_s": timestamp,
                        "event_type": selected_type,
                        "positive_target": "new_event",
                        "source_annotation_time_s": None,
                    }
                )
            elif target == "existing_annotation":
                source_time, source_type = self._nearest(item, selected_target)
                updates.update(
                    {
                        "timestamp_s": source_time,
                        "event_type": source_type,
                        "positive_target": "existing_annotation",
                        "source_annotation_time_s": source_time,
                    }
                )
            else:
                raise ReviewSessionError(f"Unknown positive target: {target}")
        elif outcome == "annotation_timestamp_corrected":
            source_time, source_type = self._nearest(item, selected_target)
            updates.update(
                {
                    "timestamp_s": timestamp,
                    "event_type": source_type,
                    "positive_target": None,
                    "source_annotation_time_s": source_time,
                }
            )
        else:
            updates.update(
                {
                    "timestamp_s": original_time,
                    "event_type": None,
                    "positive_target": None,
                    "source_annotation_time_s": None,
                }
            )
        item.update(updates)
        self.save()
        return item

    def clear_decision(self, *, confirm: bool = False) -> dict[str, Any]:
        item = self._require_current()
        self._check_revisit(item, confirm)
        item["status"] = "unreviewed"
        item["outcome"] = "unreviewed"
        item["timestamp_s"] = item["original_timestamp_s"]
        item["event_type"] = None
        item["positive_target"] = None
        item["source_annotation_time_s"] = None
        item["reviewed_at"] = None
        item["review_notes"] = None
        self.save()
        return item

    def set_note(self, note: str | None, *, confirm: bool = False) -> dict[str, Any]:
        item = self._require_current()
        self._check_revisit(item, confirm)
        if note is not None and not isinstance(note, str):
            raise ReviewSessionError("Review notes must be text.")
        value = note.strip() if note else None
        item["review_notes"] = value
        self.save()
        return item

    def save(self) -> Path:
        self.payload["review_updated_at"] = _now()
        validate_review_queue(self.payload, output=True)
        _atomic_write(self.output_path, self.payload)
        return self.output_path


__all__ = [
    "POSITIVE_TARGETS",
    "REVIEW_OUTCOMES",
    "REVIEW_QUEUE_FORMAT",
    "REVIEW_STATUSES",
    "ReviewSelection",
    "ReviewSession",
    "ReviewSessionError",
    "load_review_queue",
    "resolve_video_paths",
    "validate_review_queue",
]
