"""Strict shared contracts for the recording pipeline.

The module contains application contracts only.  Durable publication and execution belong to the
backend and later pipeline milestones.  ``DataRevision`` describes ``manifest.json``; its concrete
payload is stored in a separate ``content.json`` file and is represented by ``EventData`` here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, TypeAlias

DATA_REVISION_SCHEMA_VERSION = "data-revision/v1"
EVENT_DATA_SCHEMA_VERSION = "event-data/v1"
VISIBLE_CARD_DATA_SCHEMA_VERSION = "visible-card-data/v1"
VISUAL_IDENTITY_DATA_SCHEMA_VERSION = "visual-identity-data/v1"
PROCESSOR_RUN_REQUEST_SCHEMA_VERSION = "processor-run-request/v1"
PROCESSOR_RUN_STATE_SCHEMA_VERSION = "processor-run-state/v1"
PIPELINE_SELECTION_SCHEMA_VERSION = "pipeline-selection/v1"
PIPELINE_SELECTION_UPDATE_SCHEMA_VERSION = "pipeline-selection-update/v1"

PIPELINE_CONTENT_TYPES = frozenset(
    {"events", "visible_cards", "visual_identities", "table_observations"}
)
PIPELINE_ORIGINS = frozenset({"processor", "manual", "corrected"})
PIPELINE_RUN_STATES = frozenset({"queued", "running", "complete", "partial", "failed"})
RUN_ITEM_STATES = frozenset({"succeeded", "failed"})
SOURCE_SCHEMA_VERSIONS = frozenset({"recording-video/v1", "synthetic-fixture/v1"})

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_EVENT_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PipelineDataContractError(ValueError):
    """Raised when a recording-pipeline contract is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    """Encode finite JSON with the repository's canonical byte rules."""

    _validate_json_value(value, "value")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the lower-case SHA-256 digest of exact bytes."""

    if not isinstance(value, bytes):
        raise TypeError("digest input must be bytes")
    return hashlib.sha256(value).hexdigest()


def _parse_json_bytes(raw: bytes, context: str) -> Any:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes")

    def reject_constant(value: str) -> None:
        raise PipelineDataContractError(f"{context} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataContractError(f"{context} contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except PipelineDataContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataContractError(f"{context} must be valid UTF-8 JSON") from error


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PipelineDataContractError(f"{context} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise PipelineDataContractError(f"{context} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PipelineDataContractError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise PipelineDataContractError(f"{field} must be a safe identifier")
    return result


def _event_type(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _EVENT_TYPE.fullmatch(result) is None:
        raise PipelineDataContractError(f"{field} must be a qualified event type")
    return result


def _qualified_identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _EVENT_TYPE.fullmatch(result) is None:
        raise PipelineDataContractError(f"{field} must be a qualified identifier")
    return result


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if _SHA256.fullmatch(result) is None:
        raise PipelineDataContractError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PipelineDataContractError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PipelineDataContractError(f"{field} must be a non-negative integer")
    return value


def _finite_number(value: Any, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineDataContractError(f"{field} must be a finite number")
    if not math.isfinite(float(value)):
        raise PipelineDataContractError(f"{field} must be a finite number")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00" if result.endswith("Z") else result)
    except ValueError as error:
        raise PipelineDataContractError(f"{field} must be an ISO-8601 timestamp") from error
    if "T" not in result or parsed.utcoffset() is None:
        raise PipelineDataContractError(f"{field} must include a UTC offset")
    if parsed.utcoffset() != timedelta(0):
        raise PipelineDataContractError(f"{field} must use UTC")
    return result


def _validate_json_value(value: Any, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PipelineDataContractError(f"{field} must contain finite JSON values")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PipelineDataContractError(f"{field} object keys must be strings")
            _validate_json_value(child, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{field}[{index}]")
        return
    raise PipelineDataContractError(f"{field} must contain JSON-compatible values")


def _json_object(value: Any, field: str, *, require_non_empty: bool = False) -> dict[str, Any]:
    data = _mapping(value, field)
    if require_non_empty and not data:
        raise PipelineDataContractError(f"{field} must not be empty")
    _validate_json_value(data, field)
    return json.loads(canonical_json_bytes(data).decode("utf-8"))


def _identifier_list(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PipelineDataContractError(f"{field} must be a list")
    if not allow_empty and not value:
        raise PipelineDataContractError(f"{field} must not be empty")
    values = tuple(_identifier(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        raise PipelineDataContractError(f"{field} must contain unique identifiers")
    return values


def _optional_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


@dataclass(frozen=True, slots=True)
class RecordingVideoSource:
    """The accepted repository-relative video used by a recording pipeline run."""

    recording_id: str
    relative_path: str
    video_sha256: str
    byte_length: int
    duration_us: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RecordingVideoSource:
        data = _mapping(raw, "recording video source")
        _strict(
            data,
            {
                "schema_version",
                "recording_id",
                "relative_path",
                "video_sha256",
                "byte_length",
                "duration_us",
            },
            "recording video source",
        )
        if data["schema_version"] != "recording-video/v1":
            raise PipelineDataContractError("recording video source has an unsupported schema")
        relative_path = _text(data["relative_path"], "source.relative_path")
        path = PurePosixPath(relative_path)
        if (
            path.is_absolute()
            or "\\" in relative_path
            or ".." in path.parts
            or "" in path.parts
            or path.name in {"", "."}
        ):
            raise PipelineDataContractError(
                "source.relative_path must be safe and repository-relative"
            )
        return cls(
            recording_id=_identifier(data["recording_id"], "source.recording_id"),
            relative_path=relative_path,
            video_sha256=_digest(data["video_sha256"], "source.video_sha256"),
            byte_length=_positive_int(data["byte_length"], "source.byte_length"),
            duration_us=_positive_int(data["duration_us"], "source.duration_us"),
        )

    @property
    def video_path(self) -> str:
        """Compatibility spelling for callers that describe the path as a video path."""

        return self.relative_path

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "recording-video/v1",
            "recording_id": self.recording_id,
            "relative_path": self.relative_path,
            "video_sha256": self.video_sha256,
            "byte_length": self.byte_length,
            "duration_us": self.duration_us,
        }


@dataclass(frozen=True, slots=True)
class SyntheticFixtureSource:
    """A deterministic non-recording source used by local component fixtures."""

    fixture_id: str
    fixture_digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SyntheticFixtureSource:
        data = _mapping(raw, "synthetic fixture source")
        _strict(
            data,
            {"schema_version", "fixture_id", "fixture_digest"},
            "synthetic fixture source",
        )
        if data["schema_version"] != "synthetic-fixture/v1":
            raise PipelineDataContractError("synthetic fixture source has an unsupported schema")
        return cls(
            fixture_id=_identifier(data["fixture_id"], "source.fixture_id"),
            fixture_digest=_digest(data["fixture_digest"], "source.fixture_digest"),
        )

    @property
    def fixture_sha256(self) -> str:
        return self.fixture_digest

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "synthetic-fixture/v1",
            "fixture_id": self.fixture_id,
            "fixture_digest": self.fixture_digest,
        }


PipelineSource: TypeAlias = RecordingVideoSource | SyntheticFixtureSource


def parse_source(raw: Mapping[str, Any]) -> PipelineSource:
    data = _mapping(raw, "source")
    version = data.get("schema_version")
    if version == "recording-video/v1":
        return RecordingVideoSource.from_mapping(data)
    if version == "synthetic-fixture/v1":
        return SyntheticFixtureSource.from_mapping(data)
    raise PipelineDataContractError("source has an unsupported schema")


@dataclass(frozen=True, slots=True)
class ModelScore:
    """One score attributed to a named model producer."""

    producer_id: str
    score: int | float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "model score") -> ModelScore:
        data = _mapping(raw, context)
        _strict(data, {"producer_id", "score"}, context)
        return cls(
            producer_id=_identifier(data["producer_id"], f"{context}.producer_id"),
            score=_finite_number(data["score"], f"{context}.score"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"producer_id": self.producer_id, "score": self.score}


@dataclass(frozen=True, slots=True)
class EventRecord:
    """One source-relative event without workflow or review state."""

    event_id: str
    event_type: str
    start_us: int
    end_us: int
    model_scores: tuple[ModelScore, ...] | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        duration_us: int = 2**63 - 1,
        context: str = "event",
    ) -> EventRecord:
        data = _mapping(raw, context)
        fields = {"event_id", "event_type", "start_us", "end_us", "model_scores"}
        _strict(data, fields if "model_scores" in data else fields - {"model_scores"}, context)
        start_us = _non_negative_int(data["start_us"], f"{context}.start_us")
        end_us = _non_negative_int(data["end_us"], f"{context}.end_us")
        if start_us > end_us or end_us > duration_us:
            raise PipelineDataContractError(f"{context} time bounds are outside the source video")
        scores: tuple[ModelScore, ...] | None = None
        if "model_scores" in data:
            raw_scores = data["model_scores"]
            if not isinstance(raw_scores, list):
                raise PipelineDataContractError(f"{context}.model_scores must be a list")
            parsed_scores = tuple(
                ModelScore.from_mapping(item, f"{context}.model_scores[{index}]")
                for index, item in enumerate(raw_scores)
            )
            if len({item.producer_id for item in parsed_scores}) != len(parsed_scores):
                raise PipelineDataContractError(
                    f"{context}.model_scores must have unique producers"
                )
            scores = parsed_scores
        return cls(
            event_id=_identifier(data["event_id"], f"{context}.event_id"),
            event_type=_event_type(data["event_type"], f"{context}.event_type"),
            start_us=start_us,
            end_us=end_us,
            model_scores=scores,
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "start_us": self.start_us,
            "end_us": self.end_us,
        }
        if self.model_scores is not None:
            value["model_scores"] = [score.to_mapping() for score in self.model_scores]
        return value


@dataclass(frozen=True, slots=True)
class EventData:
    """The first concrete pipeline content payload."""

    events: tuple[EventRecord, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, duration_us: int = 2**63 - 1) -> EventData:
        data = _mapping(raw, "event data")
        _strict(data, {"schema_version", "events"}, "event data")
        if data["schema_version"] != EVENT_DATA_SCHEMA_VERSION:
            raise PipelineDataContractError("event data has an unsupported schema")
        raw_events = data["events"]
        if not isinstance(raw_events, list):
            raise PipelineDataContractError("event data.events must be a list")
        events = tuple(
            EventRecord.from_mapping(item, duration_us=duration_us, context=f"events[{index}]")
            for index, item in enumerate(raw_events)
        )
        if len({item.event_id for item in events}) != len(events):
            raise PipelineDataContractError("event data event IDs must be unique")
        order = [(item.start_us, item.end_us, item.event_id) for item in events]
        if order != sorted(order):
            raise PipelineDataContractError("event data.events must be stably ordered")
        return cls(events=events)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": EVENT_DATA_SCHEMA_VERSION,
            "events": [event.to_mapping() for event in self.events],
        }


def parse_event_data_bytes(raw: bytes, *, duration_us: int = 2**63 - 1) -> EventData:
    """Parse event content; pass the source duration when validating a revision."""

    value = _parse_json_bytes(raw, "event data")
    return EventData.from_mapping(_mapping(value, "event data"), duration_us=duration_us)


def canonical_event_data_bytes(value: EventData | Mapping[str, Any]) -> bytes:
    if isinstance(value, EventData):
        data = value
    else:
        raw = _mapping(value, "event data")
        data = EventData.from_mapping(raw)
    return canonical_json_bytes(data.to_mapping())


@dataclass(frozen=True, slots=True)
class ProcessorProducer:
    run_id: str
    processor_type: str
    implementation_id: str
    model_id: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProcessorProducer:
        data = _mapping(raw, "processor producer")
        expected = {"kind", "processor_type", "run_id", "implementation_id", "model_id"}
        _strict(
            data, expected if "model_id" in data else expected - {"model_id"}, "processor producer"
        )
        if data["kind"] != "processor":
            raise PipelineDataContractError("producer kind is not processor")
        return cls(
            run_id=_identifier(data["run_id"], "producer.run_id"),
            processor_type=_identifier(data["processor_type"], "producer.processor_type"),
            implementation_id=_qualified_identifier(
                data["implementation_id"], "producer.implementation_id"
            ),
            model_id=(
                None
                if data.get("model_id") is None
                else _qualified_identifier(data["model_id"], "producer.model_id")
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": "processor",
            "processor_type": self.processor_type,
            "run_id": self.run_id,
            "implementation_id": self.implementation_id,
        }
        if self.model_id is not None:
            value["model_id"] = self.model_id
        return value


@dataclass(frozen=True, slots=True)
class ImportProducer:
    run_id: str
    artifact_id: str
    artifact_sha256: str
    source_schema: str
    model_id: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ImportProducer:
        data = _mapping(raw, "import producer")
        expected = {"kind", "run_id", "artifact_id", "artifact_sha256", "source_schema", "model_id"}
        _strict(
            data, expected if "model_id" in data else expected - {"model_id"}, "import producer"
        )
        if data["kind"] != "import":
            raise PipelineDataContractError("producer kind is not import")
        source_schema = _text(data["source_schema"], "producer.source_schema")
        return cls(
            run_id=_identifier(data["run_id"], "producer.run_id"),
            artifact_id=_identifier(data["artifact_id"], "producer.artifact_id"),
            artifact_sha256=_digest(data["artifact_sha256"], "producer.artifact_sha256"),
            source_schema=source_schema,
            model_id=(
                None
                if data.get("model_id") is None
                else _qualified_identifier(data["model_id"], "producer.model_id")
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": "import",
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "source_schema": self.source_schema,
        }
        if self.model_id is not None:
            value["model_id"] = self.model_id
        return value


@dataclass(frozen=True, slots=True)
class HumanProducer:
    review_id: str
    operator_id: str
    base_revision_id: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> HumanProducer:
        data = _mapping(raw, "human producer")
        expected = {"kind", "review_id", "operator_id", "base_revision_id"}
        _strict(
            data,
            expected if "base_revision_id" in data else expected - {"base_revision_id"},
            "human producer",
        )
        if data["kind"] != "human":
            raise PipelineDataContractError("producer kind is not human")
        return cls(
            review_id=_identifier(data["review_id"], "producer.review_id"),
            operator_id=_identifier(data["operator_id"], "producer.operator_id"),
            base_revision_id=_optional_identifier(
                data.get("base_revision_id"), "producer.base_revision_id"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": "human",
            "review_id": self.review_id,
            "operator_id": self.operator_id,
        }
        if self.base_revision_id is not None:
            value["base_revision_id"] = self.base_revision_id
        return value


RevisionProducer: TypeAlias = ProcessorProducer | ImportProducer | HumanProducer


def _parse_producer(raw: Mapping[str, Any]) -> RevisionProducer:
    data = _mapping(raw, "producer")
    kind = data.get("kind")
    if kind == "processor":
        return ProcessorProducer.from_mapping(data)
    if kind == "import":
        return ImportProducer.from_mapping(data)
    if kind == "human":
        return HumanProducer.from_mapping(data)
    raise PipelineDataContractError("producer has an unsupported kind")


@dataclass(frozen=True, slots=True)
class DataRevision:
    """The immutable ``manifest.json`` envelope for one pipeline data revision."""

    revision_id: str
    content_type: str
    content_schema: str
    recording_id: str | None
    source: PipelineSource
    content_sha256: str
    input_revision_ids: tuple[str, ...]
    origin: str
    producer: RevisionProducer
    coverage: dict[str, Any]
    created_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DataRevision:
        data = _mapping(raw, "data revision")
        source = parse_source(_mapping(data.get("source"), "data revision.source"))
        recording_source = isinstance(source, RecordingVideoSource)
        expected = {
            "schema_version",
            "revision_id",
            "content_type",
            "content_schema",
            "source",
            "content_sha256",
            "input_revision_ids",
            "origin",
            "producer",
            "coverage",
            "created_at",
            "recording_id",
        }
        _strict(
            data,
            expected if recording_source else expected - {"recording_id"},
            "data revision",
        )
        if data["schema_version"] != DATA_REVISION_SCHEMA_VERSION:
            raise PipelineDataContractError("data revision has an unsupported schema")
        content_type = _text(data["content_type"], "content_type")
        if content_type not in PIPELINE_CONTENT_TYPES:
            raise PipelineDataContractError("content_type is unsupported")
        content_schema = _text(data["content_schema"], "content_schema")
        supported_schema = {
            "events": EVENT_DATA_SCHEMA_VERSION,
            "visible_cards": VISIBLE_CARD_DATA_SCHEMA_VERSION,
            "visual_identities": VISUAL_IDENTITY_DATA_SCHEMA_VERSION,
        }.get(content_type)
        if supported_schema is None or content_schema != supported_schema:
            raise PipelineDataContractError("content_type and content_schema do not match")
        recording_id = (
            _identifier(data["recording_id"], "recording_id") if recording_source else None
        )
        if recording_source and recording_id != source.recording_id:
            raise PipelineDataContractError("recording_id must match source.recording_id")
        input_revision_ids = _identifier_list(data["input_revision_ids"], "input_revision_ids")
        revision_id = _identifier(data["revision_id"], "revision_id")
        if revision_id in input_revision_ids:
            raise PipelineDataContractError("a revision cannot list itself as an input")
        origin = _text(data["origin"], "origin")
        if origin not in PIPELINE_ORIGINS:
            raise PipelineDataContractError("origin is unsupported")
        producer = _parse_producer(_mapping(data["producer"], "producer"))
        if origin == "processor" and not isinstance(producer, (ProcessorProducer, ImportProducer)):
            raise PipelineDataContractError("processor origin requires processor or import lineage")
        if origin in {"manual", "corrected"} and not isinstance(producer, HumanProducer):
            raise PipelineDataContractError("manual and corrected origins require human lineage")
        if origin == "manual" and producer.base_revision_id is not None:
            raise PipelineDataContractError("manual revisions cannot carry a base revision")
        if origin == "corrected" and producer.base_revision_id is None:
            raise PipelineDataContractError("corrected revisions require a base revision")
        coverage = _json_object(data["coverage"], "coverage")
        created_at = _utc_timestamp(data["created_at"], "created_at")
        return cls(
            revision_id=revision_id,
            content_type=content_type,
            content_schema=content_schema,
            recording_id=recording_id,
            source=source,
            content_sha256=_digest(data["content_sha256"], "content_sha256"),
            input_revision_ids=input_revision_ids,
            origin=origin,
            producer=producer,
            coverage=coverage,
            created_at=created_at,
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": DATA_REVISION_SCHEMA_VERSION,
            "revision_id": self.revision_id,
            "content_type": self.content_type,
            "content_schema": self.content_schema,
            "source": self.source.to_mapping(),
            "content_sha256": self.content_sha256,
            "input_revision_ids": list(self.input_revision_ids),
            "origin": self.origin,
            "producer": self.producer.to_mapping(),
            "coverage": self.coverage,
            "created_at": self.created_at,
        }
        if self.recording_id is not None:
            value["recording_id"] = self.recording_id
        return value


DataRevisionManifest = DataRevision


def validate_event_revision_content(manifest: DataRevision, content: EventData) -> None:
    """Validate the event payload against its source and declared content digest."""

    if manifest.content_type != "events" or manifest.content_schema != EVENT_DATA_SCHEMA_VERSION:
        raise PipelineDataContractError("manifest does not describe event data")
    duration_us = (
        manifest.source.duration_us
        if isinstance(manifest.source, RecordingVideoSource)
        else 2**63 - 1
    )
    validated = EventData.from_mapping(content.to_mapping(), duration_us=duration_us)
    content_bytes = canonical_json_bytes(validated.to_mapping())
    if sha256_bytes(content_bytes) != manifest.content_sha256:
        raise PipelineDataContractError("content_sha256 does not match canonical event content")
    if manifest.origin in {"manual", "corrected"} and any(
        event.model_scores is not None for event in validated.events
    ):
        raise PipelineDataContractError("human event revisions cannot carry model scores")


@dataclass(frozen=True, slots=True)
class EventDataRevision:
    """A manifest and its separately stored event content."""

    manifest: DataRevision
    content: EventData

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EventDataRevision:
        data = _mapping(raw, "event data revision")
        _strict(data, {"manifest", "content"}, "event data revision")
        manifest = DataRevision.from_mapping(_mapping(data["manifest"], "manifest"))
        duration_us = (
            manifest.source.duration_us
            if isinstance(manifest.source, RecordingVideoSource)
            else 2**63 - 1
        )
        content = EventData.from_mapping(
            _mapping(data["content"], "content"), duration_us=duration_us
        )
        validate_event_revision_content(manifest, content)
        return cls(manifest=manifest, content=content)

    def to_mapping(self) -> dict[str, Any]:
        return {"manifest": self.manifest.to_mapping(), "content": self.content.to_mapping()}


def parse_data_revision_bytes(raw: bytes, content_bytes: bytes | None = None) -> DataRevision:
    """Parse a revision manifest and optionally validate its separate content file."""

    manifest = DataRevision.from_mapping(
        _mapping(_parse_json_bytes(raw, "data revision"), "data revision")
    )
    if content_bytes is not None and manifest.content_type == "events":
        content = EventData.from_mapping(
            _mapping(_parse_json_bytes(content_bytes, "event data"), "event data"),
            duration_us=(
                manifest.source.duration_us
                if isinstance(manifest.source, RecordingVideoSource)
                else 2**63 - 1
            ),
        )
        validate_event_revision_content(manifest, content)
    return manifest


def parse_data_revision_manifest_bytes(raw: bytes) -> DataRevision:
    return parse_data_revision_bytes(raw)


def canonical_data_revision_bytes(value: DataRevision | Mapping[str, Any]) -> bytes:
    revision = value if isinstance(value, DataRevision) else DataRevision.from_mapping(value)
    return canonical_json_bytes(revision.to_mapping())


canonical_data_revision_manifest_bytes = canonical_data_revision_bytes


def parse_event_data_revision_bytes(raw: bytes) -> EventDataRevision:
    return EventDataRevision.from_mapping(
        _mapping(_parse_json_bytes(raw, "event data revision"), "event data revision")
    )


def canonical_event_data_revision_bytes(value: EventDataRevision | Mapping[str, Any]) -> bytes:
    revision = (
        value if isinstance(value, EventDataRevision) else EventDataRevision.from_mapping(value)
    )
    return canonical_json_bytes(revision.to_mapping())


@dataclass(frozen=True, slots=True)
class ImplementationIdentity:
    name: str
    version: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ImplementationIdentity:
        data = _mapping(raw, "implementation")
        _strict(data, {"name", "version"}, "implementation")
        return cls(
            name=_text(data["name"], "implementation.name"),
            version=_text(data["version"], "implementation.version"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    name: str
    version: str
    weights_sha256: str | None = None
    preprocessing: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ModelIdentity:
        data = _mapping(raw, "model")
        present_optional = {key for key in ("weights_sha256", "preprocessing") if key in data}
        _strict(data, {"name", "version", *present_optional}, "model")
        weights = data.get("weights_sha256")
        preprocessing = data.get("preprocessing")
        return cls(
            name=_text(data["name"], "model.name"),
            version=_text(data["version"], "model.version"),
            weights_sha256=None if weights is None else _digest(weights, "model.weights_sha256"),
            preprocessing=None
            if preprocessing is None
            else _text(preprocessing, "model.preprocessing"),
        )

    def to_mapping(self) -> dict[str, str]:
        value = {"name": self.name, "version": self.version}
        if self.weights_sha256 is not None:
            value["weights_sha256"] = self.weights_sha256
        if self.preprocessing is not None:
            value["preprocessing"] = self.preprocessing
        return value


def _policy(value: Any, field: str, *, allow_none: bool) -> dict[str, Any] | None:
    if value is None:
        if allow_none:
            return None
        raise PipelineDataContractError(f"{field} must be a complete policy object")
    data = _json_object(value, field, require_non_empty=True)
    policy_id = data.get("policy_id")
    if policy_id is None:
        raise PipelineDataContractError(f"{field}.policy_id is required")
    _qualified_identifier(policy_id, f"{field}.policy_id")
    return data


@dataclass(frozen=True, slots=True)
class ProcessorRunRequest:
    """The immutable request identity for one processor execution."""

    run_id: str
    processor_type: str
    source: RecordingVideoSource
    input_revision_ids: tuple[str, ...]
    implementation: ImplementationIdentity
    model: ModelIdentity | None
    configuration: dict[str, Any]
    extraction_policy: dict[str, Any]
    crop_policy: dict[str, Any] | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProcessorRunRequest:
        data = _mapping(raw, "processor run request")
        expected = {
            "schema_version",
            "run_id",
            "processor_type",
            "source",
            "input_revision_ids",
            "implementation",
            "model",
            "configuration",
            "extraction_policy",
            "crop_policy",
        }
        _strict(
            data, expected if "model" in data else expected - {"model"}, "processor run request"
        )
        if data["schema_version"] != PROCESSOR_RUN_REQUEST_SCHEMA_VERSION:
            raise PipelineDataContractError("processor run request has an unsupported schema")
        source = RecordingVideoSource.from_mapping(_mapping(data["source"], "source"))
        extraction_policy = _policy(
            data["extraction_policy"], "extraction_policy", allow_none=False
        )
        assert extraction_policy is not None
        return cls(
            run_id=_identifier(data["run_id"], "run_id"),
            processor_type=_identifier(data["processor_type"], "processor_type"),
            source=source,
            input_revision_ids=_identifier_list(data["input_revision_ids"], "input_revision_ids"),
            implementation=ImplementationIdentity.from_mapping(
                _mapping(data["implementation"], "implementation")
            ),
            model=(
                None
                if data.get("model") is None
                else ModelIdentity.from_mapping(_mapping(data["model"], "model"))
            ),
            configuration=_json_object(data["configuration"], "configuration"),
            extraction_policy=extraction_policy,
            crop_policy=_policy(data["crop_policy"], "crop_policy", allow_none=True),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": PROCESSOR_RUN_REQUEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "processor_type": self.processor_type,
            "source": self.source.to_mapping(),
            "input_revision_ids": list(self.input_revision_ids),
            "implementation": self.implementation.to_mapping(),
            "configuration": self.configuration,
            "extraction_policy": self.extraction_policy,
            "crop_policy": self.crop_policy,
        }
        if self.model is not None:
            value["model"] = self.model.to_mapping()
        return value


def parse_processor_run_request_bytes(raw: bytes) -> ProcessorRunRequest:
    return ProcessorRunRequest.from_mapping(
        _mapping(_parse_json_bytes(raw, "processor run request"), "processor run request")
    )


def canonical_processor_run_request_bytes(
    value: ProcessorRunRequest | Mapping[str, Any],
) -> bytes:
    request = (
        value if isinstance(value, ProcessorRunRequest) else ProcessorRunRequest.from_mapping(value)
    )
    return canonical_json_bytes(request.to_mapping())


@dataclass(frozen=True, slots=True)
class RunProgress:
    completed: int
    total: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RunProgress:
        data = _mapping(raw, "progress")
        _strict(data, {"completed", "total"}, "progress")
        completed = _non_negative_int(data["completed"], "progress.completed")
        total = _non_negative_int(data["total"], "progress.total")
        if completed > total:
            raise PipelineDataContractError("progress.completed cannot exceed progress.total")
        return cls(completed=completed, total=total)

    def to_mapping(self) -> dict[str, int]:
        return {"completed": self.completed, "total": self.total}


@dataclass(frozen=True, slots=True)
class RunFailure:
    code: str
    message: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "failure") -> RunFailure:
        data = _mapping(raw, context)
        _strict(data, {"code", "message"}, context)
        return cls(
            code=_identifier(data["code"], f"{context}.code"),
            message=_text(data["message"], f"{context}.message"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class RunItemOutcome:
    item_id: str
    status: str
    result: dict[str, Any] | None
    failure: RunFailure | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "item") -> RunItemOutcome:
        data = _mapping(raw, context)
        _strict(data, {"item_id", "status", "result", "failure"}, context)
        status = _text(data["status"], f"{context}.status")
        result = (
            None if data["result"] is None else _json_object(data["result"], f"{context}.result")
        )
        failure = (
            None
            if data["failure"] is None
            else RunFailure.from_mapping(
                _mapping(data["failure"], f"{context}.failure"), f"{context}.failure"
            )
        )
        if status not in RUN_ITEM_STATES:
            raise PipelineDataContractError(f"{context}.status is unsupported")
        if (status == "succeeded") != (result is not None and failure is None):
            raise PipelineDataContractError(f"{context} result/failure does not match status")
        if status == "failed" and failure is None:
            raise PipelineDataContractError(f"{context} failed outcome requires failure")
        return cls(
            item_id=_identifier(data["item_id"], f"{context}.item_id"),
            status=status,
            result=result,
            failure=failure,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "status": self.status,
            "result": self.result,
            "failure": None if self.failure is None else self.failure.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ProcessorRunState:
    """Durable execution state separate from review state."""

    run_id: str
    status: str
    attempt: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str
    progress: RunProgress
    items: tuple[RunItemOutcome, ...]
    terminal_failure: RunFailure | None
    output_revision_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProcessorRunState:
        data = _mapping(raw, "processor run state")
        _strict(
            data,
            {
                "schema_version",
                "run_id",
                "status",
                "attempt",
                "created_at",
                "started_at",
                "completed_at",
                "updated_at",
                "progress",
                "items",
                "terminal_failure",
                "output_revision_ids",
            },
            "processor run state",
        )
        if data["schema_version"] != PROCESSOR_RUN_STATE_SCHEMA_VERSION:
            raise PipelineDataContractError("processor run state has an unsupported schema")
        status = _text(data["status"], "status")
        if status not in PIPELINE_RUN_STATES:
            raise PipelineDataContractError("status is unsupported")
        created_at = _utc_timestamp(data["created_at"], "created_at")
        started_at = (
            None if data["started_at"] is None else _utc_timestamp(data["started_at"], "started_at")
        )
        completed_at = (
            None
            if data["completed_at"] is None
            else _utc_timestamp(data["completed_at"], "completed_at")
        )
        updated_at = _utc_timestamp(data["updated_at"], "updated_at")
        if started_at is not None and started_at < created_at:
            raise PipelineDataContractError("started_at cannot precede created_at")
        if completed_at is not None and (started_at is None or completed_at < started_at):
            raise PipelineDataContractError("completed_at must follow started_at")
        if updated_at < created_at:
            raise PipelineDataContractError("updated_at cannot precede created_at")
        items = (
            tuple(
                RunItemOutcome.from_mapping(item, f"items[{index}]")
                for index, item in enumerate(data["items"])
            )
            if isinstance(data["items"], list)
            else None
        )
        if items is None:
            raise PipelineDataContractError("items must be a list")
        if len({item.item_id for item in items}) != len(items):
            raise PipelineDataContractError("items must have unique IDs")
        terminal_failure = (
            None
            if data["terminal_failure"] is None
            else RunFailure.from_mapping(
                _mapping(data["terminal_failure"], "terminal_failure"), "terminal_failure"
            )
        )
        output_revision_ids = _identifier_list(data["output_revision_ids"], "output_revision_ids")
        progress = RunProgress.from_mapping(_mapping(data["progress"], "progress"))
        if status == "queued" and (
            started_at is not None
            or completed_at is not None
            or terminal_failure is not None
            or output_revision_ids
        ):
            raise PipelineDataContractError(
                "queued runs cannot have execution outputs or timestamps"
            )
        if status == "running" and (
            started_at is None
            or completed_at is not None
            or terminal_failure is not None
            or output_revision_ids
        ):
            raise PipelineDataContractError("running state has invalid timestamps or failure")
        if status == "complete" and (
            started_at is None
            or completed_at is None
            or terminal_failure is not None
            or not output_revision_ids
        ):
            raise PipelineDataContractError(
                "complete state requires timestamps and output revisions"
            )
        if status == "partial" and (
            started_at is None
            or completed_at is None
            or terminal_failure is not None
            or output_revision_ids
        ):
            raise PipelineDataContractError("partial state has invalid timestamps or outputs")
        if status == "failed" and (
            started_at is None
            or completed_at is None
            or terminal_failure is None
            or output_revision_ids
        ):
            raise PipelineDataContractError(
                "failed state requires a terminal failure and no outputs"
            )
        if status == "complete" and progress.completed != progress.total:
            raise PipelineDataContractError("complete state progress must be complete")
        if status == "complete" and any(item.status != "succeeded" for item in items):
            raise PipelineDataContractError("complete state cannot contain failed item outcomes")
        return cls(
            run_id=_identifier(data["run_id"], "run_id"),
            status=status,
            attempt=_positive_int(data["attempt"], "attempt"),
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            updated_at=updated_at,
            progress=progress,
            items=items,
            terminal_failure=terminal_failure,
            output_revision_ids=output_revision_ids,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PROCESSOR_RUN_STATE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
            "progress": self.progress.to_mapping(),
            "items": [item.to_mapping() for item in self.items],
            "terminal_failure": None
            if self.terminal_failure is None
            else self.terminal_failure.to_mapping(),
            "output_revision_ids": list(self.output_revision_ids),
        }


ProcessorRunResult = ProcessorRunState


def parse_processor_run_state_bytes(raw: bytes) -> ProcessorRunState:
    return ProcessorRunState.from_mapping(
        _mapping(_parse_json_bytes(raw, "processor run state"), "processor run state")
    )


def canonical_processor_run_state_bytes(
    value: ProcessorRunState | Mapping[str, Any],
) -> bytes:
    state = value if isinstance(value, ProcessorRunState) else ProcessorRunState.from_mapping(value)
    return canonical_json_bytes(state.to_mapping())


@dataclass(frozen=True, slots=True)
class PipelineSelection:
    """The current convenience pointers for one recording and content type."""

    revision: int
    recording_id: str
    content_type: str
    selected_generated_revision_id: str | None
    selected_completed_reference_revision_id: str | None
    updated_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineSelection:
        data = _mapping(raw, "pipeline selection")
        _strict(
            data,
            {
                "schema_version",
                "revision",
                "recording_id",
                "content_type",
                "selected_generated_revision_id",
                "selected_completed_reference_revision_id",
                "updated_at",
            },
            "pipeline selection",
        )
        if data["schema_version"] != PIPELINE_SELECTION_SCHEMA_VERSION:
            raise PipelineDataContractError("pipeline selection has an unsupported schema")
        content_type = _text(data["content_type"], "content_type")
        if content_type not in PIPELINE_CONTENT_TYPES:
            raise PipelineDataContractError("selection content_type is unsupported")
        generated = _optional_identifier(
            data["selected_generated_revision_id"], "selected_generated_revision_id"
        )
        completed = _optional_identifier(
            data["selected_completed_reference_revision_id"],
            "selected_completed_reference_revision_id",
        )
        if generated is not None and completed is not None and generated == completed:
            raise PipelineDataContractError(
                "generated and completed selection pointers must differ"
            )
        return cls(
            revision=_non_negative_int(data["revision"], "revision"),
            recording_id=_identifier(data["recording_id"], "recording_id"),
            content_type=content_type,
            selected_generated_revision_id=generated,
            selected_completed_reference_revision_id=completed,
            updated_at=_utc_timestamp(data["updated_at"], "updated_at"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_SELECTION_SCHEMA_VERSION,
            "revision": self.revision,
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "selected_generated_revision_id": self.selected_generated_revision_id,
            "selected_completed_reference_revision_id": (
                self.selected_completed_reference_revision_id
            ),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class PipelineSelectionUpdate:
    """An optimistic update command for a selection pointer."""

    expected_revision: int
    selected_generated_revision_id: str | None
    selected_completed_reference_revision_id: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineSelectionUpdate:
        data = _mapping(raw, "pipeline selection update")
        _strict(
            data,
            {
                "schema_version",
                "expected_revision",
                "selected_generated_revision_id",
                "selected_completed_reference_revision_id",
            },
            "pipeline selection update",
        )
        if data["schema_version"] != PIPELINE_SELECTION_UPDATE_SCHEMA_VERSION:
            raise PipelineDataContractError("pipeline selection update has an unsupported schema")
        generated = _optional_identifier(
            data["selected_generated_revision_id"], "selected_generated_revision_id"
        )
        completed = _optional_identifier(
            data["selected_completed_reference_revision_id"],
            "selected_completed_reference_revision_id",
        )
        if generated is not None and completed is not None and generated == completed:
            raise PipelineDataContractError(
                "generated and completed selection pointers must differ"
            )
        return cls(
            expected_revision=_non_negative_int(data["expected_revision"], "expected_revision"),
            selected_generated_revision_id=generated,
            selected_completed_reference_revision_id=completed,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_SELECTION_UPDATE_SCHEMA_VERSION,
            "expected_revision": self.expected_revision,
            "selected_generated_revision_id": self.selected_generated_revision_id,
            "selected_completed_reference_revision_id": (
                self.selected_completed_reference_revision_id
            ),
        }


def parse_pipeline_selection_bytes(raw: bytes) -> PipelineSelection:
    return PipelineSelection.from_mapping(
        _mapping(_parse_json_bytes(raw, "pipeline selection"), "pipeline selection")
    )


def canonical_pipeline_selection_bytes(
    value: PipelineSelection | Mapping[str, Any],
) -> bytes:
    selection = (
        value if isinstance(value, PipelineSelection) else PipelineSelection.from_mapping(value)
    )
    return canonical_json_bytes(selection.to_mapping())


def parse_pipeline_selection_update_bytes(raw: bytes) -> PipelineSelectionUpdate:
    return PipelineSelectionUpdate.from_mapping(
        _mapping(_parse_json_bytes(raw, "pipeline selection update"), "pipeline selection update")
    )


def canonical_pipeline_selection_update_bytes(
    value: PipelineSelectionUpdate | Mapping[str, Any],
) -> bytes:
    update = (
        value
        if isinstance(value, PipelineSelectionUpdate)
        else PipelineSelectionUpdate.from_mapping(value)
    )
    return canonical_json_bytes(update.to_mapping())


__all__ = [
    "DATA_REVISION_SCHEMA_VERSION",
    "EVENT_DATA_SCHEMA_VERSION",
    "VISIBLE_CARD_DATA_SCHEMA_VERSION",
    "VISUAL_IDENTITY_DATA_SCHEMA_VERSION",
    "PIPELINE_CONTENT_TYPES",
    "PIPELINE_ORIGINS",
    "PIPELINE_RUN_STATES",
    "PIPELINE_SELECTION_SCHEMA_VERSION",
    "PIPELINE_SELECTION_UPDATE_SCHEMA_VERSION",
    "PROCESSOR_RUN_REQUEST_SCHEMA_VERSION",
    "PROCESSOR_RUN_STATE_SCHEMA_VERSION",
    "DataRevision",
    "DataRevisionManifest",
    "EventData",
    "EventDataRevision",
    "EventRecord",
    "HumanProducer",
    "ImplementationIdentity",
    "ImportProducer",
    "ModelIdentity",
    "ModelScore",
    "PipelineDataContractError",
    "PipelineSelection",
    "PipelineSelectionUpdate",
    "ProcessorProducer",
    "ProcessorRunRequest",
    "ProcessorRunResult",
    "ProcessorRunState",
    "RecordingVideoSource",
    "RunFailure",
    "RunItemOutcome",
    "RunProgress",
    "SyntheticFixtureSource",
    "canonical_data_revision_bytes",
    "canonical_data_revision_manifest_bytes",
    "canonical_event_data_bytes",
    "canonical_event_data_revision_bytes",
    "canonical_json_bytes",
    "canonical_pipeline_selection_bytes",
    "canonical_pipeline_selection_update_bytes",
    "canonical_processor_run_request_bytes",
    "canonical_processor_run_state_bytes",
    "parse_data_revision_bytes",
    "parse_data_revision_manifest_bytes",
    "parse_event_data_bytes",
    "parse_event_data_revision_bytes",
    "parse_pipeline_selection_bytes",
    "parse_pipeline_selection_update_bytes",
    "parse_processor_run_request_bytes",
    "parse_processor_run_state_bytes",
    "parse_source",
    "sha256_bytes",
    "validate_event_revision_content",
]
