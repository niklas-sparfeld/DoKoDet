"""Freeze dataset inputs from immutable recording-pipeline revisions.

This boundary is separate from the legacy package-backed dataset adapters.  It accepts one
completed maintained reference, explicit upstream reference revisions, and explicit source facts.
It validates the complete selection before publishing one immutable dataset manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .pipeline_data import (
    DataRevision,
    EventData,
    RecordingVideoSource,
    canonical_data_revision_bytes,
)

PIPELINE_DATASET_SCHEMA_VERSION = "pipeline-dataset/v1"
PIPELINE_DATASET_TASKS = frozenset({"events", "visible_cards", "visual_identities"})
PIPELINE_DATASET_PARTITIONS = frozenset({"train", "validation", "test", "evaluation"})
PIPELINE_DATASET_SOURCE_PERMISSIONS = frozenset(
    {"training_only", "training_and_evaluation", "project_use", "unrestricted"}
)
PIPELINE_DATASET_SOURCE_RETENTION_STATES = frozenset(
    {"active", "deletion_requested", "deleted", "retired"}
)
PIPELINE_DATASET_REFERENCE_ORIGINS = frozenset({"manual", "corrected"})
PIPELINE_DATASET_REFERENCE_COVERAGE_SCHEMA = "pipeline-reference-coverage/v1"
PIPELINE_DATASET_TARGET_STATE = "reviewed_reference"
PIPELINE_DATASET_ROBUSTNESS_ROLE = "robustness_comparison"
_SAFE_IDENTIFIER = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")
_QUALIFIED_IDENTIFIER = _SAFE_IDENTIFIER | {"/"}
_DIGEST_LENGTH = 64


class PipelineDatasetError(ValueError):
    """A dataset selection or publication is invalid."""


class PipelineRevisionCatalog(Protocol):
    """The small immutable revision-store interface used by this lower-level adapter."""

    def require(self, revision_id: str) -> Any:
        """Return a stored revision or raise when it is not available."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PipelineDatasetError("dataset values must be finite JSON") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PipelineDatasetError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or any(character not in _SAFE_IDENTIFIER for character in result):
        raise PipelineDatasetError(f"{field} must be a safe identifier")
    return result


def _qualified(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or any(character not in _QUALIFIED_IDENTIFIER for character in result):
        raise PipelineDatasetError(f"{field} must be a qualified identifier")
    return result


def _digest_text(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) != _DIGEST_LENGTH or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise PipelineDatasetError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PipelineDatasetError(f"{field} must be an object")
    return value


def _unique_strings(value: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise PipelineDatasetError(f"{field} must not contain duplicates")
    return tuple(sorted(result))


def _copy_json(value: Any, field: str) -> dict[str, Any]:
    data = _mapping(value, field)
    if not data:
        raise PipelineDatasetError(f"{field} must not be empty")
    copied = json.loads(_canonical(dict(data)).decode("utf-8"))
    if not isinstance(copied, dict):  # pragma: no cover - guarded by _mapping
        raise PipelineDatasetError(f"{field} must be an object")
    return copied


def _policy_map(value: Any) -> dict[str, Any]:
    policies = _copy_json(value, "policies")
    for name, policy in policies.items():
        if not isinstance(name, str) or not name.strip():
            raise PipelineDatasetError("policy names must be non-empty strings")
        policy_data = _mapping(policy, f"policies.{name}")
        _qualified(policy_data.get("policy_id"), f"policies.{name}.policy_id")
    return policies


def _group_keys(value: Sequence[Sequence[str]]) -> tuple[tuple[str, str], ...]:
    groups: list[tuple[str, str]] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise PipelineDatasetError(f"group_keys[{index}] must contain a name and value")
        groups.append(
            (
                _identifier(pair[0], f"group_keys[{index}].name"),
                _identifier(pair[1], f"group_keys[{index}].value"),
            )
        )
    if len(groups) != len(set(groups)):
        raise PipelineDatasetError("group_keys must not contain duplicates")
    return tuple(sorted(groups))


@dataclass(frozen=True, slots=True)
class PipelineDatasetSourceGroup:
    """Immutable source permission and leakage-group facts for one recording."""

    recording_id: str
    source_asset_id: str
    source_sha256: str
    group_keys: tuple[tuple[str, str], ...]
    source_permission: str
    allowed_uses: tuple[str, ...]
    retention_state: str = "active"
    task_selected: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PipelineDatasetSourceGroup":
        data = _mapping(value, "source_group")
        expected = {
            "recording_id",
            "source_asset_id",
            "source_sha256",
            "group_keys",
            "source_permission",
            "allowed_uses",
            "retention_state",
            "task_selected",
        }
        if set(data) != expected:
            raise PipelineDatasetError("source_group has invalid fields")
        raw_groups = data["group_keys"]
        if not isinstance(raw_groups, list):
            raise PipelineDatasetError("source_group.group_keys must be a list")
        raw_uses = data["allowed_uses"]
        if not isinstance(raw_uses, list):
            raise PipelineDatasetError("source_group.allowed_uses must be a list")
        return cls(
            recording_id=data["recording_id"],
            source_asset_id=data["source_asset_id"],
            source_sha256=data["source_sha256"],
            group_keys=_group_keys(raw_groups),
            source_permission=data["source_permission"],
            allowed_uses=tuple(raw_uses),
            retention_state=data["retention_state"],
            task_selected=data["task_selected"],
        )

    def __post_init__(self) -> None:
        _identifier(self.recording_id, "source_group.recording_id")
        _identifier(self.source_asset_id, "source_group.source_asset_id")
        _digest_text(self.source_sha256, "source_group.source_sha256")
        _group_keys(self.group_keys)
        if self.source_permission not in PIPELINE_DATASET_SOURCE_PERMISSIONS:
            raise PipelineDatasetError("source_group.source_permission is invalid")
        uses = _unique_strings(self.allowed_uses, "source_group.allowed_uses")
        if not uses or any(use not in PIPELINE_DATASET_PARTITIONS for use in uses):
            raise PipelineDatasetError("source_group.allowed_uses is invalid")
        if self.retention_state not in PIPELINE_DATASET_SOURCE_RETENTION_STATES:
            raise PipelineDatasetError("source_group.retention_state is invalid")
        if not isinstance(self.task_selected, bool):
            raise PipelineDatasetError("source_group.task_selected must be a boolean")
        object.__setattr__(self, "group_keys", _group_keys(self.group_keys))
        object.__setattr__(self, "allowed_uses", uses)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "source_asset_id": self.source_asset_id,
            "source_sha256": self.source_sha256,
            "group_keys": [list(pair) for pair in self.group_keys],
            "source_permission": self.source_permission,
            "allowed_uses": list(self.allowed_uses),
            "retention_state": self.retention_state,
            "task_selected": self.task_selected,
        }


@dataclass(frozen=True, slots=True)
class PipelineDatasetRequest:
    """The explicit selection that a dataset consumer is allowed to materialize."""

    task: str
    reference_revision_id: str
    selected_input_revision_ids: tuple[str, ...]
    source_groups: tuple[PipelineDatasetSourceGroup, ...]
    policies: Mapping[str, Any]
    partition: str
    robustness_input_revision_id: str | None = None
    protected_groups: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PipelineDatasetRequest":
        data = _mapping(value, "dataset request")
        expected = {
            "task",
            "reference_revision_id",
            "selected_input_revision_ids",
            "source_groups",
            "policies",
            "partition",
            "robustness_input_revision_id",
            "protected_groups",
        }
        if set(data) != expected:
            raise PipelineDatasetError("dataset request has invalid fields")
        raw_inputs = data["selected_input_revision_ids"]
        raw_groups = data["source_groups"]
        raw_protected = data["protected_groups"]
        if not isinstance(raw_inputs, list) or not isinstance(raw_groups, list):
            raise PipelineDatasetError(
                "dataset request revision IDs and source groups must be lists"
            )
        if not isinstance(raw_protected, list):
            raise PipelineDatasetError("dataset request protected_groups must be a list")
        return cls(
            task=data["task"],
            reference_revision_id=data["reference_revision_id"],
            selected_input_revision_ids=tuple(raw_inputs),
            source_groups=tuple(
                PipelineDatasetSourceGroup.from_mapping(item) for item in raw_groups
            ),
            policies=data["policies"],
            partition=data["partition"],
            robustness_input_revision_id=data["robustness_input_revision_id"],
            protected_groups=_group_keys(raw_protected),
        )

    def __post_init__(self) -> None:
        if self.task not in PIPELINE_DATASET_TASKS:
            raise PipelineDatasetError("dataset task is unsupported")
        _identifier(self.reference_revision_id, "reference_revision_id")
        inputs = tuple(
            _identifier(value, f"selected_input_revision_ids[{index}]")
            for index, value in enumerate(self.selected_input_revision_ids)
        )
        if len(inputs) != len(set(inputs)):
            raise PipelineDatasetError("selected_input_revision_ids must not contain duplicates")
        if self.partition not in PIPELINE_DATASET_PARTITIONS:
            raise PipelineDatasetError("dataset partition is unsupported")
        if not self.source_groups:
            raise PipelineDatasetError("dataset needs at least one source group")
        if any(not isinstance(group, PipelineDatasetSourceGroup) for group in self.source_groups):
            raise PipelineDatasetError("dataset source groups are invalid")
        if self.robustness_input_revision_id is not None:
            robustness = _identifier(
                self.robustness_input_revision_id, "robustness_input_revision_id"
            )
            if robustness in inputs or robustness == self.reference_revision_id:
                raise PipelineDatasetError("robustness input must be a distinct revision")
            object.__setattr__(self, "robustness_input_revision_id", robustness)
        protected = _group_keys(self.protected_groups)
        object.__setattr__(self, "selected_input_revision_ids", inputs)
        object.__setattr__(self, "source_groups", tuple(self.source_groups))
        object.__setattr__(self, "policies", _policy_map(self.policies))
        object.__setattr__(self, "protected_groups", protected)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "reference_revision_id": self.reference_revision_id,
            "selected_input_revision_ids": list(self.selected_input_revision_ids),
            "source_groups": [group.to_mapping() for group in self.source_groups],
            "policies": dict(self.policies),
            "partition": self.partition,
            "robustness_input_revision_id": self.robustness_input_revision_id,
            "protected_groups": [list(pair) for pair in self.protected_groups],
        }


def _content_mapping(stored: Any) -> Mapping[str, Any]:
    content = getattr(stored, "content", None)
    if content is None or not hasattr(content, "to_mapping"):
        raise PipelineDatasetError("revision content is unavailable")
    return _mapping(content.to_mapping(), "revision content")


def _active_content_mapping(stored: Any) -> Mapping[str, Any]:
    """Return content after applying the active event contract."""

    manifest = _manifest(stored)
    content = _content_mapping(stored)
    if manifest.content_type != "events":
        return content
    try:
        return EventData.from_mapping(content).to_mapping()
    except (TypeError, ValueError) as error:
        raise PipelineDatasetError("event dataset content uses a retired event type") from error


def _manifest(stored: Any) -> DataRevision:
    value = getattr(stored, "manifest", None)
    if not isinstance(value, DataRevision):
        raise PipelineDatasetError("revision manifest is unavailable")
    return value


def _require(catalog: PipelineRevisionCatalog, revision_id: str) -> Any:
    try:
        return catalog.require(revision_id)
    except Exception as error:  # Catalog implementations use different not-found exceptions.
        raise PipelineDatasetError(f"pipeline revision is unavailable: {revision_id}") from error


def _revision_lineage(stored: Any) -> dict[str, Any]:
    manifest = _manifest(stored)
    return {
        "revision_id": manifest.revision_id,
        "content_type": manifest.content_type,
        "content_sha256": manifest.content_sha256,
        "manifest_sha256": hashlib.sha256(canonical_data_revision_bytes(manifest)).hexdigest(),
        "origin": manifest.origin,
        "input_revision_ids": list(manifest.input_revision_ids),
    }


def _source_for(
    manifest: DataRevision, request: PipelineDatasetRequest
) -> PipelineDatasetSourceGroup:
    if not isinstance(manifest.source, RecordingVideoSource) or manifest.recording_id is None:
        raise PipelineDatasetError("dataset references must use an accepted recording video")
    if len(request.source_groups) != 1:
        raise PipelineDatasetError("mixed source groups are not allowed in one dataset slice")
    source_group = request.source_groups[0]
    if source_group.recording_id != manifest.recording_id:
        raise PipelineDatasetError("dataset source group does not match the recording")
    if source_group.source_sha256 != manifest.source.video_sha256:
        raise PipelineDatasetError("dataset source digest does not match the recording video")
    if source_group.retention_state != "active":
        raise PipelineDatasetError("dataset source is not active")
    if not source_group.task_selected:
        raise PipelineDatasetError("dataset source task enrollment is not selected")
    if request.partition not in source_group.allowed_uses:
        raise PipelineDatasetError(
            f"dataset source does not permit the {request.partition} partition"
        )
    protected = set(request.protected_groups)
    if protected.intersection(source_group.group_keys) and request.partition in {
        "train",
        "validation",
    }:
        raise PipelineDatasetError("dataset source group is protected from development data")
    return source_group


def _coverage(reference: DataRevision, content: Mapping[str, Any]) -> Mapping[str, Any]:
    coverage = _mapping(reference.coverage, "reference coverage")
    if coverage.get("schema_version") != PIPELINE_DATASET_REFERENCE_COVERAGE_SCHEMA:
        raise PipelineDatasetError("reference coverage is missing or unsupported")
    if reference.content_type == "events":
        if coverage.get("kind") != "event_intervals":
            raise PipelineDatasetError("event reference coverage is incomplete")
        source = reference.source
        if not isinstance(source, RecordingVideoSource):
            raise PipelineDatasetError("event reference needs a recording source")
        if coverage.get("source_duration_us") != source.duration_us:
            raise PipelineDatasetError("event reference coverage does not match source duration")
        intervals = coverage.get("intervals")
        if not isinstance(intervals, list):
            raise PipelineDatasetError("event reference coverage intervals are invalid")
        cursor = 0
        for interval in intervals:
            item = _mapping(interval, "reference coverage interval")
            start = item.get("start_us")
            end = item.get("end_us")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < cursor
                or end < start
                or end > source.duration_us
            ):
                raise PipelineDatasetError("event reference coverage intervals are invalid")
            if start > cursor:
                raise PipelineDatasetError("event reference coverage has an uncovered interval")
            cursor = max(cursor, end)
        if cursor < source.duration_us:
            raise PipelineDatasetError("event reference coverage has an uncovered interval")
    elif reference.content_type == "visible_cards":
        if coverage.get("kind") != "visible_frames" or not isinstance(coverage.get("frames"), list):
            raise PipelineDatasetError("visible-card reference coverage is incomplete")
        frame_keys = {
            _canonical(item.get("frame_identity"))
            for item in coverage["frames"]
            if isinstance(item, Mapping) and item.get("frame_identity") is not None
        }
        for outcome in content.get("outcomes", []):
            if not isinstance(outcome, Mapping) or outcome.get("frame_identity") is None:
                raise PipelineDatasetError("visible-card target is missing its frame identity")
            if _canonical(outcome["frame_identity"]) not in frame_keys:
                raise PipelineDatasetError("visible-card target is outside reviewed coverage")
    elif reference.content_type == "visual_identities":
        cards = coverage.get("cards")
        if coverage.get("kind") != "visual_identities" or not isinstance(cards, list):
            raise PipelineDatasetError("visual identity reference coverage is incomplete")
        card_ids = {
            item.get("card_id")
            for item in cards
            if isinstance(item, Mapping) and isinstance(item.get("card_id"), str)
        }
        for outcome in content.get("outcomes", []):
            if not isinstance(outcome, Mapping) or outcome.get("card_id") not in card_ids:
                raise PipelineDatasetError("visual identity target is outside reviewed coverage")
    return coverage


def _policy(policies: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    for name in names:
        value = policies.get(name)
        if isinstance(value, Mapping):
            return value
    raise PipelineDatasetError(f"dataset is missing the {names[0]} policy")


def _validate_frame_policy(frame: Mapping[str, Any], policies: Mapping[str, Any]) -> None:
    policy = _policy(policies, "frame", "frame_policy", "extraction")
    if frame.get("policy") != policy.get("policy_id"):
        raise PipelineDatasetError("frame policy does not match the frozen dataset policy")


def _targets(
    task: str,
    content: Mapping[str, Any],
    source: PipelineDatasetSourceGroup,
    policies: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if task == "events":
        return [
            {
                "target_id": event["event_id"],
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "start_us": event["start_us"],
                "end_us": event["end_us"],
                "target_state": PIPELINE_DATASET_TARGET_STATE,
            }
            for event in content.get("events", [])
            if isinstance(event, Mapping)
        ]
    outcomes = content.get("outcomes")
    if not isinstance(outcomes, list):
        raise PipelineDatasetError("dataset reference content has no outcomes")
    targets: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            raise PipelineDatasetError("dataset reference outcome is invalid")
        frame = outcome.get("frame_identity")
        if not isinstance(frame, Mapping):
            raise PipelineDatasetError("dataset outcome has no frame identity")
        if frame.get("source_video_sha256") != source.source_sha256:
            raise PipelineDatasetError("dataset target frame belongs to another source video")
        _validate_frame_policy(frame, policies)
        if task == "visible_cards":
            if outcome.get("status") != "detected":
                continue
            candidates = outcome.get("candidates")
            if not isinstance(candidates, list):
                raise PipelineDatasetError("visible-card target candidates are invalid")
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    raise PipelineDatasetError("visible-card target candidate is invalid")
                targets.append(
                    {
                        "target_id": candidate["card_id"],
                        "event_id": outcome["event_id"],
                        "card_id": candidate["card_id"],
                        "frame_identity": dict(frame),
                        "geometry": candidate["geometry"],
                        "target": dict(candidate),
                        "target_state": PIPELINE_DATASET_TARGET_STATE,
                    }
                )
            continue
        crop = outcome.get("crop_identity")
        if outcome.get("status") != "classified":
            continue
        if not isinstance(crop, Mapping):
            raise PipelineDatasetError("visual identity target has no crop identity")
        crop_policy = _policy(policies, "crop", "crop_policy")
        if crop.get("crop_policy") != crop_policy.get("policy_id"):
            raise PipelineDatasetError("crop policy does not match the frozen dataset policy")
        candidates = outcome.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PipelineDatasetError("visual identity target has no selected identity")
        selected = candidates[0]
        if not isinstance(selected, Mapping):
            raise PipelineDatasetError("visual identity target is invalid")
        targets.append(
            {
                "target_id": outcome["card_id"],
                "card_id": outcome["card_id"],
                "frame_identity": dict(frame),
                "crop_identity": dict(crop),
                "identity": selected["identity"],
                "target_state": PIPELINE_DATASET_TARGET_STATE,
            }
        )
    return targets


def _validate_alignment(
    task: str,
    reference: Any,
    inputs: Sequence[Any],
    policies: Mapping[str, Any],
) -> None:
    reference_manifest = _manifest(reference)
    reference_content = _active_content_mapping(reference)
    if task == "events":
        if inputs:
            raise PipelineDatasetError("event dataset does not accept implicit input revisions")
        return
    if len(inputs) != 1:
        raise PipelineDatasetError("dataset needs one explicit upstream reference revision")
    upstream_manifest = _manifest(inputs[0])
    upstream_content = _active_content_mapping(inputs[0])
    if upstream_manifest.origin not in PIPELINE_DATASET_REFERENCE_ORIGINS:
        raise PipelineDatasetError("dataset upstream revisions must be completed references")
    if upstream_manifest.recording_id != reference_manifest.recording_id:
        raise PipelineDatasetError("dataset input and target belong to different recordings")
    if task == "visible_cards":
        if upstream_manifest.content_type != "events":
            raise PipelineDatasetError("visible-card dataset input must be an event reference")
        event_ids = {
            event.get("event_id")
            for event in upstream_content.get("events", [])
            if isinstance(event, Mapping)
        }
        outcome_ids = {
            outcome.get("event_id")
            for outcome in reference_content.get("outcomes", [])
            if isinstance(outcome, Mapping)
        }
        if outcome_ids != event_ids:
            raise PipelineDatasetError("visible-card targets do not align with event inputs")
        return
    if upstream_manifest.content_type != "visible_cards":
        raise PipelineDatasetError("identity dataset input must be a visible-card reference")
    visible_cards = {
        candidate.get("card_id"): (outcome.get("frame_identity"), candidate.get("geometry"))
        for outcome in upstream_content.get("outcomes", [])
        if isinstance(outcome, Mapping) and outcome.get("status") == "detected"
        for candidate in outcome.get("candidates", [])
        if isinstance(candidate, Mapping)
    }
    identity_outcomes = {
        outcome.get("card_id"): outcome
        for outcome in reference_content.get("outcomes", [])
        if isinstance(outcome, Mapping)
    }
    if set(identity_outcomes) != set(visible_cards):
        raise PipelineDatasetError("identity targets do not align with visible-card inputs")
    for card_id, outcome in identity_outcomes.items():
        expected = visible_cards[card_id]
        if outcome.get("frame_identity") != expected[0] or outcome.get("geometry") != expected[1]:
            raise PipelineDatasetError(f"identity target geometry is not aligned for {card_id}")
    _policy(policies, "crop", "crop_policy")


def _validate_robustness(reference: Any, robustness: Any | None) -> None:
    if robustness is None:
        return
    reference_manifest = _manifest(reference)
    robustness_manifest = _manifest(robustness)
    if robustness_manifest.origin != "processor":
        raise PipelineDatasetError("robustness input must be a generated processor revision")
    if (
        robustness_manifest.content_type != reference_manifest.content_type
        or robustness_manifest.recording_id != reference_manifest.recording_id
        or not isinstance(robustness_manifest.source, RecordingVideoSource)
        or not isinstance(reference_manifest.source, RecordingVideoSource)
        or robustness_manifest.source.video_sha256 != reference_manifest.source.video_sha256
    ):
        raise PipelineDatasetError("robustness input does not match the reviewed source")


def _stable_manifest(
    request: PipelineDatasetRequest,
    reference: Any,
    inputs: Sequence[Any],
    robustness: Any | None,
    source_group: PipelineDatasetSourceGroup,
) -> dict[str, Any]:
    reference_manifest = _manifest(reference)
    reference_content = _content_mapping(reference)
    if reference_manifest.origin not in PIPELINE_DATASET_REFERENCE_ORIGINS:
        raise PipelineDatasetError("dataset target must come from a completed reference")
    if reference_manifest.content_type != request.task:
        raise PipelineDatasetError("reference content type does not match the dataset task")
    coverage = _coverage(reference_manifest, reference_content)
    _source_for(reference_manifest, request)
    _validate_alignment(request.task, reference, inputs, request.policies)
    _validate_robustness(reference, robustness)
    targets = _targets(request.task, reference_content, source_group, request.policies)
    lineages = {"reference": _revision_lineage(reference)}
    if inputs:
        lineages["inputs"] = [_revision_lineage(item) for item in inputs]
    if robustness is not None:
        lineages["robustness"] = _revision_lineage(robustness)
    source_groups = [source_group.to_mapping()]
    return {
        "schema_version": PIPELINE_DATASET_SCHEMA_VERSION,
        "task": request.task,
        "recording_id": reference_manifest.recording_id,
        "selected_revisions": {
            "completed_reference": reference_manifest.revision_id,
            "inputs": [_manifest(item).revision_id for item in inputs],
            "robustness": None
            if robustness is None
            else _manifest(robustness).revision_id,
        },
        "selected_reference_revision_id": reference_manifest.revision_id,
        "selected_input_revision_ids": [_manifest(item).revision_id for item in inputs],
        "robustness_inputs": []
        if robustness is None
        else [
            {
                "revision_id": _manifest(robustness).revision_id,
                "role": PIPELINE_DATASET_ROBUSTNESS_ROLE,
            }
        ],
        "source_groups": source_groups,
        "partition": request.partition,
        "protected_groups": [list(pair) for pair in request.protected_groups],
        "policies": request.policies,
        "coverage": coverage,
        "targets": targets,
        "lineage": lineages,
    }


def build_pipeline_dataset(
    revision_catalog: PipelineRevisionCatalog,
    request: PipelineDatasetRequest,
) -> dict[str, Any]:
    """Validate one explicit selection and return its frozen manifest payload."""

    if not isinstance(request, PipelineDatasetRequest):
        raise PipelineDatasetError("dataset request is invalid")
    reference = _require(revision_catalog, request.reference_revision_id)
    inputs = [_require(revision_catalog, value) for value in request.selected_input_revision_ids]
    robustness = (
        None
        if request.robustness_input_revision_id is None
        else _require(revision_catalog, request.robustness_input_revision_id)
    )
    source_group = _source_for(_manifest(reference), request)
    stable = _stable_manifest(request, reference, inputs, robustness, source_group)
    dataset_digest = _digest(stable)
    return {
        **stable,
        "dataset_id": f"pipeline-dataset-{dataset_digest[:24]}",
        "dataset_digest": dataset_digest,
        "state": "frozen",
    }


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise PipelineDatasetError(f"refusing to overwrite dataset manifest: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise PipelineDatasetError(f"could not publish dataset manifest: {path}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def materialize_pipeline_dataset(
    revision_catalog: PipelineRevisionCatalog,
    request: PipelineDatasetRequest,
    output_root: str | Path,
) -> dict[str, Any]:
    """Validate and publish one immutable dataset manifest without reading package media."""

    manifest = build_pipeline_dataset(revision_catalog, request)
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "dataset-manifest.json"
    _write_immutable_json(manifest_path, manifest)
    return {
        "status": "completed",
        "dataset_id": manifest["dataset_id"],
        "dataset_digest": manifest["dataset_digest"],
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "target_count": len(manifest["targets"]),
    }


def load_pipeline_dataset_manifest(path: str | Path) -> dict[str, Any]:
    """Load one frozen pipeline dataset manifest and verify its digest."""

    manifest_path = Path(path)
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PipelineDatasetError(f"could not read dataset manifest: {manifest_path}") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != PIPELINE_DATASET_SCHEMA_VERSION
    ):
        raise PipelineDatasetError("dataset manifest schema is unsupported")
    digest = value.get("dataset_digest")
    stable = {
        key: item
        for key, item in value.items()
        if key not in {"dataset_id", "dataset_digest", "state"}
    }
    if digest != _digest(stable):
        raise PipelineDatasetError("dataset manifest digest does not match its contents")
    if value.get("state") != "frozen":
        raise PipelineDatasetError("dataset manifest is not frozen")
    return value


def build_event_dataset(
    revision_catalog: PipelineRevisionCatalog,
    request: PipelineDatasetRequest,
) -> dict[str, Any]:
    """Build the event dataset projection from an explicit completed event reference."""

    if request.task != "events":
        raise PipelineDatasetError("event dataset request has the wrong task")
    return build_pipeline_dataset(revision_catalog, request)


def build_visible_card_dataset(
    revision_catalog: PipelineRevisionCatalog,
    request: PipelineDatasetRequest,
) -> dict[str, Any]:
    """Build the visible-card dataset projection from explicit event and card references."""

    if request.task != "visible_cards":
        raise PipelineDatasetError("visible-card dataset request has the wrong task")
    return build_pipeline_dataset(revision_catalog, request)


def build_visual_identity_dataset(
    revision_catalog: PipelineRevisionCatalog,
    request: PipelineDatasetRequest,
) -> dict[str, Any]:
    """Build the identity dataset projection from explicit visible-card and identity references."""

    if request.task != "visual_identities":
        raise PipelineDatasetError("identity dataset request has the wrong task")
    return build_pipeline_dataset(revision_catalog, request)


build_visual_card_identity_dataset = build_visual_identity_dataset


class PipelineDatasetConsumer:
    """Convenience facade used by local commands and backend adapters."""

    def __init__(self, revision_catalog: PipelineRevisionCatalog) -> None:
        self.revision_catalog = revision_catalog

    def build(self, request: PipelineDatasetRequest) -> dict[str, Any]:
        return build_pipeline_dataset(self.revision_catalog, request)

    def materialize(
        self, request: PipelineDatasetRequest, output_root: str | Path
    ) -> dict[str, Any]:
        return materialize_pipeline_dataset(self.revision_catalog, request, output_root)


__all__ = [
    "PIPELINE_DATASET_PARTITIONS",
    "PIPELINE_DATASET_REFERENCE_COVERAGE_SCHEMA",
    "PIPELINE_DATASET_ROBUSTNESS_ROLE",
    "PIPELINE_DATASET_SCHEMA_VERSION",
    "PIPELINE_DATASET_TARGET_STATE",
    "PipelineDatasetConsumer",
    "PipelineDatasetError",
    "PipelineDatasetRequest",
    "PipelineDatasetSourceGroup",
    "build_event_dataset",
    "build_pipeline_dataset",
    "build_visible_card_dataset",
    "build_visual_card_identity_dataset",
    "build_visual_identity_dataset",
    "load_pipeline_dataset_manifest",
    "materialize_pipeline_dataset",
]
