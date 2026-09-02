"""Prepare immutable visual-card identity review batches.

The completed visible-card review is the only source of identity geometry.  This module copies
deterministic identity crops below the operations workspace and records classifier output as a
proposal.  A proposal is never a label and a classifier failure does not prevent manual review.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError
from table_evidence_analyzer import CARD_IDENTITIES, CardClassificationResult
from table_evidence_analyzer.visible_card_review_freeze import (
    apply_visible_card_crop_policy,
    frozen_visible_card_crop_policy,
    load_frozen_visible_card_crop_policy,
)
from table_evidence_analyzer.visible_card_review_workflow import (
    VisibleCardReviewQueue,
    VisibleCardReviewWorkflowError,
    load_visible_card_review_queue,
    validate_completed_visible_card_review_queue,
)

VISUAL_CARD_IDENTITY_REVIEW_SCHEMA_VERSION = "visual-card-identity-review/v1"
VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION = "visual-card-identity-review-batch/v1"
VISUAL_CARD_IDENTITY_ITEM_SCHEMA_VERSION = "visual-card-identity-review-item/v1"
VISUAL_CARD_IDENTITY_PROPOSAL_SCHEMA_VERSION = "visual-card-identity-proposal/v1"
VISUAL_CARD_IDENTITY_DECISION_SCHEMA_VERSION = "visual-card-identity-decision/v1"
VISUAL_CARD_IDENTITY_COVERAGE_SCHEMA_VERSION = "visual-card-identity-review-coverage/v1"

VISUAL_CARD_IDENTITY_BATCH_SCHEMA = VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION
VISUAL_CARD_IDENTITY_BATCH_STATUSES = frozenset({"preparing", "ready", "failed", "blocked"})
VISUAL_CARD_IDENTITY_BATCH_PHASES = frozenset(
    {"validating_inputs", "materializing_crops", "running_proposals", "ready", "failed", "blocked"}
)
VISUAL_CARD_IDENTITY_FAILURE_CODES = frozenset(
    {
        "missing_visible_card_review",
        "stale_visible_card_review",
        "protected_source_group",
        "missing_source_frame",
        "source_frame_digest_mismatch",
        "source_frame_invalid",
        "crop_error",
        "no_identity_usable_cards",
        "identity_classifier_unavailable",
        "identity_classifier_error",
        "write_error",
    }
)
VISUAL_CARD_IDENTITY_CROP_POLICY_ID = "raw_rectangular"
_IDENTIFIER_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-/"
)
_SHA256_LENGTH = 64


class VisualCardIdentityBatchError(ValueError):
    """Raised when an identity review batch or its source is invalid."""


class VisualCardIdentityBatchConflict(VisualCardIdentityBatchError):
    """Raised when a frozen identity review input changed."""


class VisualCardIdentityBatchWriteError(RuntimeError):
    """Raised when an identity review artifact cannot be written atomically."""


class VisualCardIdentityClassifier(Protocol):
    """Small runtime boundary used by identity batch preparation."""

    name: str
    version: str
    calibration: str

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        """Return a classifier proposal for one deterministic PPM crop."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise VisualCardIdentityBatchError("value is not canonical JSON") from error


def _digest_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise VisualCardIdentityBatchError(
            f"could not read immutable source frame: {path}"
        ) from error


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character not in _IDENTIFIER_CHARACTERS for character in value)
    ):
        raise VisualCardIdentityBatchError(f"{field} must be a simple non-empty identifier")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualCardIdentityBatchError(f"{field} must be a non-empty string")
    return value


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VisualCardIdentityBatchError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    if not result.endswith("Z"):
        raise VisualCardIdentityBatchError(f"{field} must use UTC with a Z suffix")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise VisualCardIdentityBatchError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.utcoffset() != datetime.now(UTC).utcoffset():
        raise VisualCardIdentityBatchError(f"{field} must use UTC")
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisualCardIdentityBatchError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise VisualCardIdentityBatchError(f"{field} must be positive")
    return result


def _finite_non_negative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisualCardIdentityBatchError(f"{field} must be finite and non-negative")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise VisualCardIdentityBatchError(f"{field} must be finite and non-negative")
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise VisualCardIdentityBatchWriteError(
            f"could not write identity artifact: {path}"
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _immutable_write(path: Path, value: bytes) -> None:
    if path.exists():
        try:
            if path.read_bytes() == value:
                return
        except OSError as error:
            raise VisualCardIdentityBatchWriteError(
                f"could not read identity artifact: {path}"
            ) from error
        raise VisualCardIdentityBatchWriteError(f"refusing to overwrite identity artifact: {path}")
    _atomic_write(path, value)


@dataclass(frozen=True, slots=True)
class VisualCardIdentityClassifierIdentity:
    """Stable, path-free identity of the configured proposal generator."""

    name: str
    version: str
    calibration: str
    bundle_identity: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _identifier(self.name, "classifier.name")
        _text(self.version, "classifier.version")
        _identifier(self.calibration, "classifier.calibration")
        if self.bundle_identity is not None:
            if not isinstance(self.bundle_identity, dict):
                raise VisualCardIdentityBatchError("classifier.bundle_identity must be an object")
            try:
                _canonical(self.bundle_identity)
            except VisualCardIdentityBatchError as error:
                raise VisualCardIdentityBatchError(
                    "classifier.bundle_identity must be JSON serializable"
                ) from error
            if "bundle_digest" in self.bundle_identity:
                _digest(
                    self.bundle_identity["bundle_digest"],
                    "classifier.bundle_identity.bundle_digest",
                )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "calibration": self.calibration,
            "bundle_identity": None if self.bundle_identity is None else dict(self.bundle_identity),
        }

    @classmethod
    def from_classifier(cls, classifier: Any) -> "VisualCardIdentityClassifierIdentity":
        if classifier is None:
            raise VisualCardIdentityBatchError("the visual card identity classifier is unavailable")
        bundle_identity = getattr(classifier, "bundle_identity", None)
        return cls(
            name=getattr(classifier, "name", None),
            version=getattr(classifier, "version", None),
            calibration=getattr(classifier, "calibration", None),
            bundle_identity=None if bundle_identity is None else dict(bundle_identity),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualCardIdentityClassifierIdentity":
        fields = {"name", "version", "calibration", "bundle_identity"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisualCardIdentityBatchError("classifier identity has unexpected fields")
        try:
            return cls(
                name=value["name"],
                version=value["version"],
                calibration=value["calibration"],
                bundle_identity=value["bundle_identity"],
            )
        except (TypeError, ValueError, VisualCardIdentityBatchError) as error:
            raise VisualCardIdentityBatchError("classifier identity is invalid") from error


@dataclass(frozen=True, slots=True)
class VisualCardIdentityBatchRequest:
    """Frozen inputs for one recording-scoped identity review batch."""

    recording_id: str
    source_asset_id: str
    source_sha256: str
    source_lineage_group: str
    visible_card_review_batch_id: str
    visible_card_review_version_id: str
    visible_card_review_version_digest: str
    visible_card_review_queue_path: Path
    visible_card_review_queue_digest: str
    classifier: VisualCardIdentityClassifierIdentity
    crop_policy_id: str = VISUAL_CARD_IDENTITY_CROP_POLICY_ID
    crop_policy: dict[str, Any] | None = None
    protected_source_lineage_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.recording_id, "recording_id")
        _identifier(self.source_asset_id, "source_asset_id")
        _digest(self.source_sha256, "source_sha256")
        _identifier(self.source_lineage_group, "source_lineage_group")
        _identifier(self.visible_card_review_batch_id, "visible_card_review_batch_id")
        _identifier(self.visible_card_review_version_id, "visible_card_review_version_id")
        _digest(self.visible_card_review_version_digest, "visible_card_review_version_digest")
        if not isinstance(self.visible_card_review_queue_path, Path):
            object.__setattr__(
                self, "visible_card_review_queue_path", Path(self.visible_card_review_queue_path)
            )
        _digest(self.visible_card_review_queue_digest, "visible_card_review_queue_digest")
        _identifier(self.crop_policy_id, "crop_policy_id")
        policy = (
            self.crop_policy if self.crop_policy is not None else frozen_visible_card_crop_policy()
        )
        try:
            validated = load_frozen_visible_card_crop_policy(policy)
        except (ValueError, OSError) as error:
            raise VisualCardIdentityBatchError(
                "crop_policy is not the frozen visible-card policy"
            ) from error
        selected = {entry["policy_id"] for entry in validated["policies"]}
        if self.crop_policy_id not in selected:
            raise VisualCardIdentityBatchError("crop_policy_id is not in the frozen crop policy")
        object.__setattr__(self, "crop_policy", validated)
        if any(
            not isinstance(value, str) or not value
            for value in self.protected_source_lineage_groups
        ):
            raise VisualCardIdentityBatchError("protected source-lineage groups are invalid")
        if len(set(self.protected_source_lineage_groups)) != len(
            self.protected_source_lineage_groups
        ):
            raise VisualCardIdentityBatchError("protected source-lineage groups must be unique")

    @property
    def identity_mapping(self) -> dict[str, Any]:
        """Return path-independent input identity for deterministic batch IDs."""

        assert self.crop_policy is not None
        return {
            "schema_version": VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "source_asset_id": self.source_asset_id,
            "source_sha256": self.source_sha256,
            "source_lineage_group": self.source_lineage_group,
            "visible_card_review_batch_id": self.visible_card_review_batch_id,
            "visible_card_review_version_id": self.visible_card_review_version_id,
            "visible_card_review_version_digest": self.visible_card_review_version_digest,
            "visible_card_review_queue_digest": self.visible_card_review_queue_digest,
            "classifier": self.classifier.to_mapping(),
            "crop_policy_id": self.crop_policy_id,
            "crop_policy": self.crop_policy,
            "protected_source_lineage_groups": list(self.protected_source_lineage_groups),
        }

    @property
    def request_digest(self) -> str:
        return _digest_value(self.identity_mapping)

    @property
    def batch_id(self) -> str:
        return f"visual-card-identity-batch-{self.request_digest[:24]}"

    def to_mapping(self) -> dict[str, Any]:
        return {
            **self.identity_mapping,
            "visible_card_review_queue_path": str(
                self.visible_card_review_queue_path.expanduser().resolve()
            ),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualCardIdentityBatchRequest":
        fields = set(
            (
                "schema_version",
                "recording_id",
                "source_asset_id",
                "source_sha256",
                "source_lineage_group",
                "visible_card_review_batch_id",
                "visible_card_review_version_id",
                "visible_card_review_version_digest",
                "visible_card_review_queue_path",
                "visible_card_review_queue_digest",
                "classifier",
                "crop_policy_id",
                "crop_policy",
                "protected_source_lineage_groups",
            )
        )
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisualCardIdentityBatchError("identity batch request has unexpected fields")
        if value["schema_version"] != VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION:
            raise VisualCardIdentityBatchError("unsupported identity batch request schema")
        try:
            return cls(
                recording_id=value["recording_id"],
                source_asset_id=value["source_asset_id"],
                source_sha256=value["source_sha256"],
                source_lineage_group=value["source_lineage_group"],
                visible_card_review_batch_id=value["visible_card_review_batch_id"],
                visible_card_review_version_id=value["visible_card_review_version_id"],
                visible_card_review_version_digest=value["visible_card_review_version_digest"],
                visible_card_review_queue_path=Path(value["visible_card_review_queue_path"]),
                visible_card_review_queue_digest=value["visible_card_review_queue_digest"],
                classifier=VisualCardIdentityClassifierIdentity.from_mapping(value["classifier"]),
                crop_policy_id=value["crop_policy_id"],
                crop_policy=value["crop_policy"],
                protected_source_lineage_groups=tuple(value["protected_source_lineage_groups"]),
            )
        except (KeyError, TypeError, ValueError, VisualCardIdentityBatchError) as error:
            raise VisualCardIdentityBatchError("identity batch request is invalid") from error


@dataclass(frozen=True, slots=True)
class VisualCardIdentityBatchFailure:
    """One explicit identity batch blocker or item failure."""

    code: str
    message: str
    stage: str
    item_id: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.code not in VISUAL_CARD_IDENTITY_FAILURE_CODES:
            raise VisualCardIdentityBatchError(f"unknown identity batch failure code: {self.code}")
        _text(self.message, "failure.message")
        _text(self.stage, "failure.stage")
        if self.item_id is not None:
            _identifier(self.item_id, "failure.item_id")
        if not isinstance(self.retryable, bool):
            raise VisualCardIdentityBatchError("failure.retryable must be a boolean")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "item_id": self.item_id,
            "retryable": self.retryable,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualCardIdentityBatchFailure":
        fields = {"code", "message", "stage", "item_id", "retryable"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisualCardIdentityBatchError("identity batch failure has unexpected fields")
        try:
            return cls(**dict(value))
        except (TypeError, ValueError, VisualCardIdentityBatchError) as error:
            raise VisualCardIdentityBatchError("identity batch failure is invalid") from error


def _decision_mapping() -> dict[str, Any]:
    return {
        "schema_version": VISUAL_CARD_IDENTITY_DECISION_SCHEMA_VERSION,
        "status": "pending",
        "identity": None,
        "reason": None,
        "reviewer": None,
        "updated_at_utc": None,
    }


def _validate_decision(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "status",
        "identity",
        "reason",
        "reviewer",
        "updated_at_utc",
    }:
        raise VisualCardIdentityBatchError("identity decision has unexpected fields")
    if value["schema_version"] != VISUAL_CARD_IDENTITY_DECISION_SCHEMA_VERSION:
        raise VisualCardIdentityBatchError("unsupported identity decision schema")
    if value["status"] != "pending" or any(
        value[field] is not None for field in ("identity", "reason", "reviewer", "updated_at_utc")
    ):
        raise VisualCardIdentityBatchError(
            "identity batch items must start with a pending decision"
        )


def _validate_candidates(candidates: Any, status: str) -> None:
    if not isinstance(candidates, list):
        raise VisualCardIdentityBatchError("identity proposal candidates are invalid")
    previous_probability = math.inf
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {"card", "probability"}:
            raise VisualCardIdentityBatchError("identity proposal candidate is invalid")
        if candidate["card"] not in CARD_IDENTITIES:
            raise VisualCardIdentityBatchError("identity proposal has an unknown card")
        probability = candidate["probability"]
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(float(probability))
            or not 0 < float(probability) <= 1
            or float(probability) > previous_probability
        ):
            raise VisualCardIdentityBatchError("identity proposal candidate probability is invalid")
        previous_probability = float(probability)
    if status == "ok" and not candidates:
        raise VisualCardIdentityBatchError("a successful identity proposal needs candidates")
    if status == "unavailable" and candidates:
        raise VisualCardIdentityBatchError(
            "an unavailable identity proposal cannot have candidates"
        )


def _validate_result_mapping(value: Any) -> None:
    fields = {
        "status",
        "candidates",
        "usage",
        "latency_ms",
        "retry_count",
        "estimated_cost_usd",
        "error",
        "raw_response",
        "cache_hit",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualCardIdentityBatchError("identity classifier result is invalid")
    if value["status"] not in {"ok", "unavailable"}:
        raise VisualCardIdentityBatchError("identity classifier result status is invalid")
    _validate_candidates(value["candidates"], value["status"])
    usage = value["usage"]
    if not isinstance(usage, Mapping) or set(usage) != {
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }:
        raise VisualCardIdentityBatchError("identity classifier usage is invalid")
    for field in usage:
        _non_negative_int(usage[field], f"identity result.usage.{field}")
    _finite_non_negative(value["latency_ms"], "identity result.latency_ms")
    _non_negative_int(value["retry_count"], "identity result.retry_count")
    _finite_non_negative(value["estimated_cost_usd"], "identity result.estimated_cost_usd")
    if not isinstance(value["cache_hit"], bool):
        raise VisualCardIdentityBatchError("identity result.cache_hit is invalid")
    if value["error"] is not None:
        _text(value["error"], "identity result.error")
    if value["raw_response"] is not None and not isinstance(value["raw_response"], Mapping):
        raise VisualCardIdentityBatchError("identity result.raw_response is invalid")


def _classifier_result_mapping(result: CardClassificationResult) -> dict[str, Any]:
    try:
        mapping = {
            "status": result.status,
            "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
            "usage": result.usage.to_mapping(),
            "latency_ms": result.latency_ms,
            "retry_count": result.retry_count,
            "estimated_cost_usd": result.estimated_cost_usd,
            "error": result.error,
            "raw_response": result.raw_response,
            "cache_hit": result.cache_hit,
        }
    except (AttributeError, TypeError, ValueError) as error:
        raise VisualCardIdentityBatchError(
            "identity classifier returned an invalid result"
        ) from error
    if not isinstance(mapping, dict) or set(mapping) != {
        "status",
        "candidates",
        "usage",
        "latency_ms",
        "retry_count",
        "estimated_cost_usd",
        "error",
        "raw_response",
        "cache_hit",
    }:
        raise VisualCardIdentityBatchError("identity classifier result has unexpected fields")
    if mapping["status"] not in {"ok", "unavailable"}:
        raise VisualCardIdentityBatchError("identity classifier result status is invalid")
    if not isinstance(mapping["candidates"], list):
        raise VisualCardIdentityBatchError("identity classifier candidates must be a list")
    previous_probability = math.inf
    for candidate in mapping["candidates"]:
        if not isinstance(candidate, Mapping) or set(candidate) != {"card", "probability"}:
            raise VisualCardIdentityBatchError("identity classifier candidate is invalid")
        if candidate["card"] not in CARD_IDENTITIES:
            raise VisualCardIdentityBatchError("identity classifier returned an unknown card")
        probability = float(candidate["probability"])
        if not math.isfinite(probability) or probability <= 0 or probability > previous_probability:
            raise VisualCardIdentityBatchError("identity classifier candidates are not ranked")
        previous_probability = probability
    if mapping["status"] == "ok" and not mapping["candidates"]:
        raise VisualCardIdentityBatchError("a successful identity proposal needs candidates")
    if mapping["status"] == "unavailable" and mapping["candidates"]:
        raise VisualCardIdentityBatchError(
            "an unavailable identity proposal cannot have candidates"
        )
    _finite_non_negative(mapping["latency_ms"], "identity result.latency_ms")
    _non_negative_int(mapping["retry_count"], "identity result.retry_count")
    _finite_non_negative(mapping["estimated_cost_usd"], "identity result.estimated_cost_usd")
    _validate_result_mapping(mapping)
    return mapping


def _proposal_mapping(
    *,
    item_id: str,
    crop_sha256: str,
    classifier: VisualCardIdentityClassifierIdentity,
    result: CardClassificationResult,
    result_path: Path,
) -> dict[str, Any]:
    result_mapping = _classifier_result_mapping(result)
    candidates = result_mapping["candidates"]
    proposal = {
        "schema_version": VISUAL_CARD_IDENTITY_PROPOSAL_SCHEMA_VERSION,
        "item_id": item_id,
        "crop_sha256": crop_sha256,
        "classifier": classifier.to_mapping(),
        "status": result_mapping["status"],
        "candidates": candidates,
        "score": candidates[0]["probability"] if candidates else None,
        "result": result_mapping,
        "result_path": str(result_path.resolve()),
    }
    proposal_bytes = _canonical(proposal) + b"\n"
    _immutable_write(result_path, proposal_bytes)
    proposal["result_digest"] = hashlib.sha256(proposal_bytes).hexdigest()
    return proposal


def _source_mapping(
    request: VisualCardIdentityBatchRequest, source: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {
        "package_id",
        "frame_part_name",
        "target_offset_ms",
        "image",
        "frame_sha256",
        "source_asset_id",
        "source_lineage_group",
        "source_asset_sha256",
        "width",
        "height",
    }
    if set(source) != fields:
        raise VisualCardIdentityBatchError("visible-card source lineage has unexpected fields")
    if source["source_asset_id"] != request.source_asset_id:
        raise VisualCardIdentityBatchError("visible-card source asset changed")
    if source["source_lineage_group"] != request.source_lineage_group:
        raise VisualCardIdentityBatchError("visible-card source lineage group changed")
    if source["source_asset_sha256"] != request.source_sha256:
        raise VisualCardIdentityBatchError("visible-card source digest changed")
    _digest(source["frame_sha256"], "source.frame_sha256")
    _positive_int(source["width"], "source.width")
    _positive_int(source["height"], "source.height")
    return dict(source)


def _coverage(queue: VisibleCardReviewQueue) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    total_cards = 0
    for item in queue.items:
        review = item.review
        for action in review.actions:
            total_cards += 1
            card = action.reviewed_card
            if action.action == "removed" or card is None:
                excluded.append(
                    {
                        "visible_card_review_item_id": item.item_id,
                        "card_id": action.card_id,
                        "reason": "removed_by_reviewer",
                    }
                )
                continue
            if review.decision != "GOOD":
                excluded.append(
                    {
                        "visible_card_review_item_id": item.item_id,
                        "card_id": card.card_id,
                        "reason": "frame_not_usable",
                    }
                )
                continue
            if not card.identity_usability.usable:
                excluded.append(
                    {
                        "visible_card_review_item_id": item.item_id,
                        "card_id": card.card_id,
                        "reason": card.identity_usability.reason,
                    }
                )
                continue
            selected.append(
                {
                    "visible_card_review_item_id": item.item_id,
                    "card_id": card.card_id,
                }
            )
    coverage_core = {
        "schema_version": VISUAL_CARD_IDENTITY_COVERAGE_SCHEMA_VERSION,
        "visible_card_review_item_count": len(queue.items),
        "reviewed_visible_card_count": total_cards,
        "identity_usable_card_count": len(selected),
        "excluded_card_count": len(excluded),
        "excluded_cards": excluded,
    }
    return selected, {**coverage_core, "coverage_digest": _digest_value(coverage_core)}


def _empty_coverage() -> dict[str, Any]:
    core = {
        "schema_version": VISUAL_CARD_IDENTITY_COVERAGE_SCHEMA_VERSION,
        "visible_card_review_item_count": 0,
        "reviewed_visible_card_count": 0,
        "identity_usable_card_count": 0,
        "excluded_card_count": 0,
        "excluded_cards": [],
    }
    return {**core, "coverage_digest": _digest_value(core)}


def _progress(items: Sequence[Mapping[str, Any]], *, phase: str, total: int) -> dict[str, Any]:
    return {
        "phase": phase,
        "total_items": total,
        "crops_materialized": sum(item.get("crop") is not None for item in items),
        "proposals_completed": sum(item.get("proposal") is not None for item in items),
        "failed_items": sum(item.get("failure") is not None for item in items),
    }


def _state(
    request: VisualCardIdentityBatchRequest,
    *,
    status: str,
    phase: str,
    created_at: str,
    items: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    failures: Sequence[VisualCardIdentityBatchFailure] = (),
) -> dict[str, Any]:
    if (
        status not in VISUAL_CARD_IDENTITY_BATCH_STATUSES
        or phase not in VISUAL_CARD_IDENTITY_BATCH_PHASES
    ):
        raise VisualCardIdentityBatchError("invalid identity batch state")
    return {
        "schema_version": VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION,
        "batch_id": request.batch_id,
        "recording_id": request.recording_id,
        "request_digest": request.request_digest,
        "status": status,
        "created_at_utc": created_at,
        "updated_at_utc": _now(),
        "frozen_inputs": request.to_mapping(),
        "classifier": request.classifier.to_mapping(),
        "crop_policy_id": request.crop_policy_id,
        "crop_policy": request.crop_policy,
        "progress": _progress(items, phase=phase, total=len(items)),
        "items": list(items),
        "coverage": dict(coverage),
        "failures": [failure.to_mapping() for failure in failures],
    }


def _validate_item(value: Any) -> None:
    fields = {
        "schema_version",
        "item_id",
        "source",
        "visible_card",
        "visible_card_digest",
        "crop",
        "proposal",
        "decision",
        "status",
        "failure",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualCardIdentityBatchError("identity review item has unexpected fields")
    if value["schema_version"] != VISUAL_CARD_IDENTITY_ITEM_SCHEMA_VERSION:
        raise VisualCardIdentityBatchError("unsupported identity review item schema")
    _identifier(value["item_id"], "item.item_id")
    _digest(value["visible_card_digest"], "item.visible_card_digest")
    if value["visible_card_digest"] != _digest_value(value["visible_card"]):
        raise VisualCardIdentityBatchError("identity item visible-card digest is invalid")
    for field in ("source", "visible_card"):
        if not isinstance(value[field], Mapping):
            raise VisualCardIdentityBatchError(f"item.{field} must be an object")
    crop = value["crop"]
    if crop is not None:
        if not isinstance(crop, Mapping) or set(crop) != {
            "path",
            "sha256",
            "byte_length",
            "content_type",
            "width",
            "height",
            "policy_id",
            "policy_digest",
        }:
            raise VisualCardIdentityBatchError("identity crop is invalid")
        _text(crop["path"], "crop.path")
        _digest(crop["sha256"], "crop.sha256")
        _positive_int(crop["byte_length"], "crop.byte_length")
        _text(crop["content_type"], "crop.content_type")
        _positive_int(crop["width"], "crop.width")
        _positive_int(crop["height"], "crop.height")
        _identifier(crop["policy_id"], "crop.policy_id")
        _digest(crop["policy_digest"], "crop.policy_digest")
        _validate_immutable_file(crop["path"], crop["sha256"], "crop")
    proposal = value["proposal"]
    if proposal is not None:
        if (
            not isinstance(proposal, Mapping)
            or set(proposal)
            != {
                "schema_version",
                "item_id",
                "crop_sha256",
                "classifier",
                "status",
                "candidates",
                "score",
                "result",
                "result_path",
                "result_digest",
            }
            or proposal.get("schema_version") != VISUAL_CARD_IDENTITY_PROPOSAL_SCHEMA_VERSION
        ):
            raise VisualCardIdentityBatchError("identity proposal is invalid")
        if proposal.get("item_id") != value["item_id"]:
            raise VisualCardIdentityBatchError("identity proposal item identity changed")
        _digest(proposal.get("crop_sha256"), "proposal.crop_sha256")
        if crop is None or proposal["crop_sha256"] != crop["sha256"]:
            raise VisualCardIdentityBatchError("identity proposal crop identity changed")
        VisualCardIdentityClassifierIdentity.from_mapping(proposal["classifier"])
        if proposal.get("status") not in {"ok", "unavailable"}:
            raise VisualCardIdentityBatchError("identity proposal status is invalid")
        if not isinstance(proposal.get("candidates"), list):
            raise VisualCardIdentityBatchError("identity proposal candidates are invalid")
        _validate_candidates(proposal["candidates"], proposal["status"])
        score = proposal.get("score")
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 < float(score) <= 1
        ):
            raise VisualCardIdentityBatchError("identity proposal score is invalid")
        if score != (proposal["candidates"][0]["probability"] if proposal["candidates"] else None):
            raise VisualCardIdentityBatchError("identity proposal score is inconsistent")
        if not isinstance(proposal.get("result"), Mapping):
            raise VisualCardIdentityBatchError("identity proposal result is invalid")
        _validate_result_mapping(proposal["result"])
        _text(proposal.get("result_path"), "proposal.result_path")
        _digest(proposal.get("result_digest"), "proposal.result_digest")
        _validate_immutable_file(proposal["result_path"], proposal["result_digest"], "proposal")
    _validate_decision(value["decision"])
    if value["status"] not in {"ready", "failed"}:
        raise VisualCardIdentityBatchError("identity item status is invalid")
    if value["failure"] is not None:
        VisualCardIdentityBatchFailure.from_mapping(value["failure"])
    if (value["status"] == "failed") != (value["failure"] is not None):
        raise VisualCardIdentityBatchError("identity item failure state is inconsistent")


def _validate_state(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version",
        "batch_id",
        "recording_id",
        "request_digest",
        "status",
        "created_at_utc",
        "updated_at_utc",
        "frozen_inputs",
        "classifier",
        "crop_policy_id",
        "crop_policy",
        "progress",
        "items",
        "coverage",
        "failures",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualCardIdentityBatchError("identity batch state has unexpected fields")
    if value["schema_version"] != VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION:
        raise VisualCardIdentityBatchError("unsupported identity batch schema")
    request = VisualCardIdentityBatchRequest.from_mapping(value["frozen_inputs"])
    if (
        value["batch_id"] != request.batch_id
        or value["recording_id"] != request.recording_id
        or value["request_digest"] != request.request_digest
    ):
        raise VisualCardIdentityBatchError("identity batch identity does not match frozen inputs")
    if value["status"] not in VISUAL_CARD_IDENTITY_BATCH_STATUSES:
        raise VisualCardIdentityBatchError("identity batch status is invalid")
    _utc_timestamp(value["created_at_utc"], "created_at_utc")
    _utc_timestamp(value["updated_at_utc"], "updated_at_utc")
    if (
        value["classifier"] != request.classifier.to_mapping()
        or value["crop_policy"] != request.crop_policy
        or value["crop_policy_id"] != request.crop_policy_id
    ):
        raise VisualCardIdentityBatchError("identity batch frozen metadata changed")
    progress = value["progress"]
    if not isinstance(progress, Mapping) or set(progress) != {
        "phase",
        "total_items",
        "crops_materialized",
        "proposals_completed",
        "failed_items",
    }:
        raise VisualCardIdentityBatchError("identity batch progress is invalid")
    if progress["phase"] not in VISUAL_CARD_IDENTITY_BATCH_PHASES:
        raise VisualCardIdentityBatchError("identity batch progress phase is invalid")
    for field in ("total_items", "crops_materialized", "proposals_completed", "failed_items"):
        _non_negative_int(progress[field], f"progress.{field}")
    if not isinstance(value["items"], list) or not isinstance(value["failures"], list):
        raise VisualCardIdentityBatchError("identity batch items and failures must be lists")
    for item in value["items"]:
        _validate_item(item)
        if item["crop"] is not None:
            if item["crop"]["policy_id"] != request.crop_policy_id:
                raise VisualCardIdentityBatchError("identity item crop policy changed")
            if item["crop"]["policy_digest"] != request.crop_policy["policy_digest"]:
                raise VisualCardIdentityBatchError("identity item crop policy digest changed")
        if item["proposal"] is not None and item["proposal"]["classifier"] != value["classifier"]:
            raise VisualCardIdentityBatchError("identity item classifier identity changed")
    item_ids = [item["item_id"] for item in value["items"]]
    if len(item_ids) != len(set(item_ids)):
        raise VisualCardIdentityBatchError("identity batch item IDs must be unique")
    _validate_coverage(value["coverage"])
    if value["status"] != "preparing" and (
        value["coverage"]["identity_usable_card_count"] != len(value["items"])
    ):
        raise VisualCardIdentityBatchError("identity coverage item count is inconsistent")
    expected_progress = _progress(
        value["items"], phase=progress["phase"], total=len(value["items"])
    )
    if dict(progress) != expected_progress:
        raise VisualCardIdentityBatchError("identity batch progress is inconsistent")
    for failure in value["failures"]:
        VisualCardIdentityBatchFailure.from_mapping(failure)
    return dict(value)


def _validate_coverage(value: Any) -> None:
    fields = {
        "schema_version",
        "visible_card_review_item_count",
        "reviewed_visible_card_count",
        "identity_usable_card_count",
        "excluded_card_count",
        "excluded_cards",
        "coverage_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualCardIdentityBatchError("identity batch coverage is invalid")
    if value["schema_version"] != VISUAL_CARD_IDENTITY_COVERAGE_SCHEMA_VERSION:
        raise VisualCardIdentityBatchError("unsupported identity coverage schema")
    for field in fields - {"schema_version", "excluded_cards", "coverage_digest"}:
        _non_negative_int(value[field], f"coverage.{field}")
    if not isinstance(value["excluded_cards"], list):
        raise VisualCardIdentityBatchError("identity coverage exclusions are invalid")
    if value["excluded_card_count"] != len(value["excluded_cards"]):
        raise VisualCardIdentityBatchError("identity coverage exclusion count is inconsistent")
    for excluded in value["excluded_cards"]:
        if not isinstance(excluded, Mapping) or set(excluded) != {
            "visible_card_review_item_id",
            "card_id",
            "reason",
        }:
            raise VisualCardIdentityBatchError("identity coverage exclusion is invalid")
        _identifier(excluded["visible_card_review_item_id"], "coverage.item_id")
        _identifier(excluded["card_id"], "coverage.card_id")
        _text(excluded["reason"], "coverage.reason")
    _digest(value["coverage_digest"], "coverage.coverage_digest")
    core = {key: value[key] for key in fields if key != "coverage_digest"}
    if value["coverage_digest"] != _digest_value(core):
        raise VisualCardIdentityBatchError("identity coverage digest is invalid")


def _validate_immutable_file(path_value: Any, expected_digest: str, kind: str) -> None:
    path = Path(path_value)
    if not path.is_file():
        raise VisualCardIdentityBatchError(f"{kind} artifact is missing: {path}")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisualCardIdentityBatchError(f"{kind} artifact cannot be read: {path}") from error
    if actual != expected_digest:
        raise VisualCardIdentityBatchError(f"{kind} artifact digest changed: {path}")


def _load_source_queue(request: VisualCardIdentityBatchRequest) -> VisibleCardReviewQueue:
    path = request.visible_card_review_queue_path
    if not path.is_file():
        raise VisualCardIdentityBatchError(
            "missing_visible_card_review: completed visible-card review is missing"
        )
    try:
        if _file_digest(path) != request.visible_card_review_queue_digest:
            raise VisualCardIdentityBatchError(
                "stale_visible_card_review: visible-card review bytes changed"
            )
        queue = validate_completed_visible_card_review_queue(load_visible_card_review_queue(path))
    except VisualCardIdentityBatchError:
        raise
    except (OSError, ValueError, VisibleCardReviewWorkflowError) as error:
        raise VisualCardIdentityBatchError(
            f"stale_visible_card_review: visible-card review is invalid: {error}"
        ) from error
    if queue.run_id != request.visible_card_review_batch_id:
        raise VisualCardIdentityBatchError(
            "stale_visible_card_review: visible-card batch identity changed"
        )
    return queue


def _selected_card(queue: VisibleCardReviewQueue, selected: Mapping[str, Any]) -> tuple[Any, Any]:
    item_id = selected["visible_card_review_item_id"]
    card_id = selected["card_id"]
    for item in queue.items:
        if item.item_id != item_id:
            continue
        for action in item.review.actions:
            if action.card_id == card_id and action.reviewed_card is not None:
                return item, action.reviewed_card
    raise VisualCardIdentityBatchError("identity coverage names a missing reviewed card")


def _new_item_id(request: VisualCardIdentityBatchRequest, item_id: str, card_id: str) -> str:
    return (
        "identity-card-"
        + _digest_value(
            {
                "batch_id": request.batch_id,
                "visible_card_review_item_id": item_id,
                "card_id": card_id,
            }
        )[:24]
    )


def _initial_item(
    request: VisualCardIdentityBatchRequest,
    queue_item: Any,
    card: Any,
) -> dict[str, Any]:
    source = _source_mapping(request, queue_item.source.to_mapping())
    item_id = _new_item_id(request, queue_item.item_id, card.card_id)
    return {
        "schema_version": VISUAL_CARD_IDENTITY_ITEM_SCHEMA_VERSION,
        "item_id": item_id,
        "source": source,
        "visible_card": card.to_mapping(),
        "visible_card_digest": _digest_value(card.to_mapping()),
        "crop": None,
        "proposal": None,
        "decision": _decision_mapping(),
        "status": "ready",
        "failure": None,
    }


def _read_source_frame(source: Mapping[str, Any]) -> bytes:
    path = Path(source["image"])
    if not path.is_file():
        raise VisualCardIdentityBatchError(
            "missing_source_frame: visible-card source frame is missing"
        )
    try:
        value = path.read_bytes()
    except OSError as error:
        raise VisualCardIdentityBatchError(
            "source_frame_invalid: visible-card source frame cannot be read"
        ) from error
    if hashlib.sha256(value).hexdigest() != source["frame_sha256"]:
        raise VisualCardIdentityBatchError(
            "source_frame_digest_mismatch: visible-card source frame changed"
        )
    try:
        with Image.open(BytesIO(value)) as image:
            if image.size != (source["width"], source["height"]):
                raise VisualCardIdentityBatchError(
                    "source_frame_invalid: source frame dimensions changed"
                )
    except (UnidentifiedImageError, OSError) as error:
        raise VisualCardIdentityBatchError(
            "source_frame_invalid: source frame is not an image"
        ) from error
    return value


def _materialize_crop(
    batch_root: Path,
    item: dict[str, Any],
    image_bytes: bytes,
    *,
    policy_id: str,
    policy_digest: str,
) -> None:
    from table_evidence_analyzer import ReviewedVisibleCard

    card = ReviewedVisibleCard.from_mapping(item["visible_card"])
    source = item["source"]
    try:
        crop_bytes = apply_visible_card_crop_policy(
            image_bytes,
            card,
            policy_id,
            width=source["width"],
            height=source["height"],
        )
    except Exception as error:
        raise VisualCardIdentityBatchError(
            f"crop_error: identity crop could not be materialized: {error}"
        ) from error
    if crop_bytes is None:
        raise VisualCardIdentityBatchError(
            "crop_error: selected identity crop policy rejected the reviewed card"
        )
    try:
        with Image.open(BytesIO(crop_bytes)) as crop:
            width, height = crop.size
    except (UnidentifiedImageError, OSError) as error:
        raise VisualCardIdentityBatchError(
            "crop_error: materialized identity crop is invalid"
        ) from error
    path = batch_root / "crops" / f"{item['item_id']}.ppm"
    _immutable_write(path, crop_bytes)
    item["crop"] = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(crop_bytes).hexdigest(),
        "byte_length": len(crop_bytes),
        "content_type": "image/x-portable-pixmap",
        "width": width,
        "height": height,
        "policy_id": policy_id,
        "policy_digest": policy_digest,
    }


def _load_existing_crop(item: Mapping[str, Any]) -> bytes | None:
    crop = item.get("crop")
    if not isinstance(crop, Mapping):
        return None
    path = Path(crop["path"])
    if not path.is_file():
        raise VisualCardIdentityBatchError("crop_error: frozen identity crop is missing")
    try:
        value = path.read_bytes()
    except OSError as error:
        raise VisualCardIdentityBatchError(
            "crop_error: frozen identity crop cannot be read"
        ) from error
    if hashlib.sha256(value).hexdigest() != crop.get("sha256"):
        raise VisualCardIdentityBatchError("crop_error: frozen identity crop bytes changed")
    return value


def _proposal_result(
    classifier: VisualCardIdentityClassifier,
    crop_bytes: bytes,
) -> CardClassificationResult:
    try:
        result = classifier.classify_ppm(crop_bytes)
    except Exception as error:
        return CardClassificationResult(
            status="unavailable", error=f"identity classifier failed: {error}"
        )
    if not isinstance(result, CardClassificationResult):
        return CardClassificationResult(
            status="unavailable", error="identity classifier returned a non-result value"
        )
    return result


def _validate_classifier_identity(
    request: VisualCardIdentityBatchRequest,
    classifier: VisualCardIdentityClassifier,
) -> None:
    try:
        actual = VisualCardIdentityClassifierIdentity.from_classifier(classifier)
    except (TypeError, ValueError, VisualCardIdentityBatchError) as error:
        raise VisualCardIdentityBatchError(
            "identity_classifier_unavailable: classifier identity is invalid"
        ) from error
    if actual != request.classifier:
        raise VisualCardIdentityBatchError(
            "identity_classifier_error: configured classifier identity changed"
        )


class VisualCardIdentityReviewBatchStore:
    """Persist one immutable-input identity preparation batch."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def batch_root(self, batch_id: str) -> Path:
        return self.workspace_root / "visual-card-identity-review-batches" / batch_id

    def batch_path(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "batch.json"

    def initialize(self, request: VisualCardIdentityBatchRequest) -> dict[str, Any]:
        """Persist a preparing state before source reads and classifier calls."""

        path = self.batch_path(request.batch_id)
        if path.is_file():
            current = load_visual_card_identity_review_batch(path)
            if current["request_digest"] != request.request_digest:
                raise VisualCardIdentityBatchError("stored identity batch request identity changed")
            return current
        state = _state(
            request,
            status="preparing",
            phase="validating_inputs",
            created_at=_now(),
            items=(),
            coverage=_empty_coverage(),
        )
        _atomic_write(path, _canonical(state) + b"\n")
        return load_visual_card_identity_review_batch(path)

    def begin_retry(self, batch_id: str) -> dict[str, Any]:
        """Return a preparing state that retains all frozen inputs and crops."""

        path = self.batch_path(batch_id)
        current = load_visual_card_identity_review_batch(path)
        if current["status"] not in {"failed", "ready"}:
            raise VisualCardIdentityBatchError(
                "only a failed or ready identity batch can be retried"
            )
        request = VisualCardIdentityBatchRequest.from_mapping(current["frozen_inputs"])
        state = dict(current)
        state.update(
            {
                "status": "preparing",
                "updated_at_utc": _now(),
                "progress": _progress(
                    current["items"], phase="running_proposals", total=len(current["items"])
                ),
                "failures": [],
            }
        )
        state["frozen_inputs"] = request.to_mapping()
        _atomic_write(path, _canonical(state) + b"\n")
        return load_visual_card_identity_review_batch(path)

    def prepare(
        self,
        request: VisualCardIdentityBatchRequest,
        classifier: VisualCardIdentityClassifier,
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Materialize reviewed identity crops and persist classifier proposals."""

        _validate_classifier_identity(request, classifier)
        state_path = self.batch_path(request.batch_id)
        current = (
            load_visual_card_identity_review_batch(state_path) if state_path.is_file() else None
        )
        if current is not None and current["request_digest"] != request.request_digest:
            raise VisualCardIdentityBatchError("stored identity batch request identity changed")
        if current is not None and current["status"] in {"blocked", "failed"} and not resume:
            return current
        if current is not None and current["status"] == "ready" and not resume:
            return current

        created_at = current["created_at_utc"] if current is not None else _now()
        try:
            if request.source_lineage_group in set(request.protected_source_lineage_groups):
                return self._terminal(
                    request,
                    status="blocked",
                    phase="blocked",
                    created_at=created_at,
                    failures=(
                        VisualCardIdentityBatchFailure(
                            "protected_source_group",
                            "The source-lineage group is protected and cannot enter "
                            "identity review.",
                            "validation",
                        ),
                    ),
                )
            queue = _load_source_queue(request)
            selected, coverage = _coverage(queue)
            if not selected:
                return self._terminal(
                    request,
                    status="blocked",
                    phase="blocked",
                    created_at=created_at,
                    coverage=coverage,
                    failures=(
                        VisualCardIdentityBatchFailure(
                            "no_identity_usable_cards",
                            "The completed visible-card review contains no identity-usable cards.",
                            "validation",
                        ),
                    ),
                )
        except VisualCardIdentityBatchError as error:
            message = str(error)
            code = message.split(":", 1)[0] if ":" in message else "stale_visible_card_review"
            if code not in VISUAL_CARD_IDENTITY_FAILURE_CODES:
                code = "stale_visible_card_review"
            return self._terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(VisualCardIdentityBatchFailure(code, message, "validation"),),
            )

        previous_items = {
            item["item_id"]: item
            for item in (current or {}).get("items", [])
            if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)
        }
        items: list[dict[str, Any]] = []
        selected_by_id: list[tuple[dict[str, Any], Any, Any]] = []
        for selected_card in selected:
            queue_item, card = _selected_card(queue, selected_card)
            initial = _initial_item(request, queue_item, card)
            previous = previous_items.get(initial["item_id"])
            item = dict(previous) if previous is not None else initial
            if previous is not None:
                item["source"] = initial["source"]
                item["visible_card"] = initial["visible_card"]
                item["decision"] = _decision_mapping()
                item["failure"] = None
                item["status"] = "ready"
            items.append(item)
            selected_by_id.append((item, queue_item, card))

        _atomic_write(
            state_path,
            _canonical(
                _state(
                    request,
                    status="preparing",
                    phase="materializing_crops",
                    created_at=created_at,
                    items=items,
                    coverage=coverage,
                )
            )
            + b"\n",
        )
        policy = request.crop_policy
        assert policy is not None
        policy_digest = policy["policy_digest"]
        failures: list[VisualCardIdentityBatchFailure] = []
        for item, _queue_item, _card in selected_by_id:
            try:
                image_bytes = _read_source_frame(item["source"])
                crop_bytes = _load_existing_crop(item) if item.get("crop") is not None else None
                if crop_bytes is None:
                    _materialize_crop(
                        self.batch_root(request.batch_id),
                        item,
                        image_bytes,
                        policy_id=request.crop_policy_id,
                        policy_digest=policy_digest,
                    )
            except (VisualCardIdentityBatchError, VisualCardIdentityBatchWriteError) as error:
                message = str(error)
                code = (
                    "write_error"
                    if isinstance(error, VisualCardIdentityBatchWriteError)
                    else message.split(":", 1)[0]
                    if ":" in message
                    else "crop_error"
                )
                if code not in VISUAL_CARD_IDENTITY_FAILURE_CODES:
                    code = "crop_error"
                failure = VisualCardIdentityBatchFailure(
                    code, message, "materializing_crops", item_id=item["item_id"], retryable=True
                )
                item["failure"] = failure.to_mapping()
                item["status"] = "failed"
                failures.append(failure)
            _atomic_write(
                state_path,
                _canonical(
                    _state(
                        request,
                        status="preparing",
                        phase="materializing_crops",
                        created_at=created_at,
                        items=items,
                        coverage=coverage,
                    )
                )
                + b"\n",
            )
        if failures:
            return self._terminal(
                request,
                status="failed",
                phase="failed",
                created_at=created_at,
                items=items,
                coverage=coverage,
                failures=failures,
            )

        _atomic_write(
            state_path,
            _canonical(
                _state(
                    request,
                    status="preparing",
                    phase="running_proposals",
                    created_at=created_at,
                    items=items,
                    coverage=coverage,
                )
            )
            + b"\n",
        )
        for item, _queue_item, _card in selected_by_id:
            existing_proposal = item.get("proposal")
            if existing_proposal is not None and not (
                resume and existing_proposal.get("status") == "unavailable"
            ):
                continue
            crop = _load_existing_crop(item)
            if crop is None:
                raise VisualCardIdentityBatchError(
                    "crop_error: identity crop disappeared during proposal generation"
                )
            attempt = 0
            if isinstance(existing_proposal, Mapping):
                attempt = int(existing_proposal.get("result", {}).get("retry_count", 0)) + 1
            suffix = f"-retry-{attempt}" if attempt else ""
            result_path = (
                self.batch_root(request.batch_id) / "proposals" / f"{item['item_id']}{suffix}.json"
            )
            try:
                result = _proposal_result(classifier, crop)
                item["proposal"] = _proposal_mapping(
                    item_id=item["item_id"],
                    crop_sha256=item["crop"]["sha256"],
                    classifier=request.classifier,
                    result=result,
                    result_path=result_path,
                )
            except VisualCardIdentityBatchWriteError as error:
                failure = VisualCardIdentityBatchFailure(
                    "write_error",
                    str(error),
                    "running_proposals",
                    item_id=item["item_id"],
                    retryable=True,
                )
                item["failure"] = failure.to_mapping()
                item["status"] = "failed"
                failures.append(failure)
            except VisualCardIdentityBatchError as error:
                failure = VisualCardIdentityBatchFailure(
                    "identity_classifier_error",
                    str(error),
                    "running_proposals",
                    item_id=item["item_id"],
                    retryable=True,
                )
                item["failure"] = failure.to_mapping()
                item["status"] = "failed"
                failures.append(failure)
            _atomic_write(
                state_path,
                _canonical(
                    _state(
                        request,
                        status="preparing",
                        phase="running_proposals",
                        created_at=created_at,
                        items=items,
                        coverage=coverage,
                    )
                )
                + b"\n",
            )
        if failures:
            return self._terminal(
                request,
                status="failed",
                phase="failed",
                created_at=created_at,
                items=items,
                coverage=coverage,
                failures=failures,
            )
        return self._terminal(
            request,
            status="ready",
            phase="ready",
            created_at=created_at,
            items=items,
            coverage=coverage,
        )

    def _terminal(
        self,
        request: VisualCardIdentityBatchRequest,
        *,
        status: str,
        phase: str,
        created_at: str,
        items: Sequence[Mapping[str, Any]] = (),
        coverage: Mapping[str, Any] | None = None,
        failures: Sequence[VisualCardIdentityBatchFailure] = (),
    ) -> dict[str, Any]:
        if coverage is None:
            coverage = _empty_coverage()
        state = _state(
            request,
            status=status,
            phase=phase,
            created_at=created_at,
            items=items,
            coverage=coverage,
            failures=failures,
        )
        _atomic_write(self.batch_path(request.batch_id), _canonical(state) + b"\n")
        return load_visual_card_identity_review_batch(self.batch_path(request.batch_id))


def load_visual_card_identity_review_batch(path: str | Path) -> dict[str, Any]:
    """Load and validate one persisted identity batch state."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualCardIdentityBatchError(f"could not read identity batch: {path}") from error
    return _validate_state(value)


def prepare_visual_card_identity_review_batch(
    workspace_root: str | Path,
    request: VisualCardIdentityBatchRequest,
    classifier: VisualCardIdentityClassifier,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """Prepare one identity review batch through the operations boundary."""

    return VisualCardIdentityReviewBatchStore(workspace_root).prepare(
        request, classifier, resume=resume
    )


def preview_visual_card_identity_review_batch(
    request: VisualCardIdentityBatchRequest,
) -> dict[str, Any]:
    """Read the completed visible-card review and return stable coverage facts."""

    queue = _load_source_queue(request)
    selected, coverage = _coverage(queue)
    return {
        "schema_version": "visual-card-identity-review-preview/v1",
        "recording_id": request.recording_id,
        "batch_id": request.batch_id,
        "request_digest": request.request_digest,
        "visible_card_review_batch_id": request.visible_card_review_batch_id,
        "visible_card_review_version_id": request.visible_card_review_version_id,
        "visible_card_review_version_digest": request.visible_card_review_version_digest,
        "visible_card_review_queue_digest": request.visible_card_review_queue_digest,
        "source_asset_id": request.source_asset_id,
        "source_sha256": request.source_sha256,
        "source_lineage_group": request.source_lineage_group,
        "classifier": request.classifier.to_mapping(),
        "crop_policy_id": request.crop_policy_id,
        "crop_policy": request.crop_policy,
        "selected_card_count": len(selected),
        "coverage": coverage,
    }


def assess_visual_card_identity_review_readiness(
    *,
    source_lineage_group: str,
    protected_source_lineage_groups: Sequence[str],
    source_review_available: bool,
    classifier_available: bool,
    selected_card_count: int,
) -> list[VisualCardIdentityBatchFailure]:
    """Return explicit recording-scoped blockers without starting batch work."""

    failures: list[VisualCardIdentityBatchFailure] = []
    if source_lineage_group in set(protected_source_lineage_groups):
        failures.append(
            VisualCardIdentityBatchFailure(
                "protected_source_group",
                "The source-lineage group is protected and cannot enter identity review.",
                "validation",
            )
        )
    if not source_review_available:
        failures.append(
            VisualCardIdentityBatchFailure(
                "missing_visible_card_review",
                "Complete and publish the visible-card review before identity review.",
                "validation",
            )
        )
    if not classifier_available:
        failures.append(
            VisualCardIdentityBatchFailure(
                "identity_classifier_unavailable",
                "The configured visual card identity classifier is not available.",
                "validation",
            )
        )
    if source_review_available and classifier_available and selected_card_count == 0:
        failures.append(
            VisualCardIdentityBatchFailure(
                "no_identity_usable_cards",
                "The completed visible-card review contains no identity-usable cards.",
                "validation",
            )
        )
    return failures


# Short aliases match the visible-card batch API and make the boundary easy to discover.
VisualCardIdentityBatchStore = VisualCardIdentityReviewBatchStore
VisualCardIdentityReviewBatchRequest = VisualCardIdentityBatchRequest
load_identity_review_batch = load_visual_card_identity_review_batch


__all__ = [
    "VISUAL_CARD_IDENTITY_BATCH_SCHEMA",
    "VISUAL_CARD_IDENTITY_BATCH_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_BATCH_PHASES",
    "VISUAL_CARD_IDENTITY_BATCH_STATUSES",
    "VISUAL_CARD_IDENTITY_CROP_POLICY_ID",
    "VISUAL_CARD_IDENTITY_COVERAGE_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_DECISION_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_FAILURE_CODES",
    "VISUAL_CARD_IDENTITY_ITEM_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_PROPOSAL_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_REVIEW_SCHEMA_VERSION",
    "VisualCardIdentityBatchConflict",
    "VisualCardIdentityBatchError",
    "VisualCardIdentityBatchFailure",
    "VisualCardIdentityBatchRequest",
    "VisualCardIdentityBatchStore",
    "VisualCardIdentityBatchWriteError",
    "VisualCardIdentityClassifier",
    "VisualCardIdentityClassifierIdentity",
    "VisualCardIdentityReviewBatchRequest",
    "VisualCardIdentityReviewBatchStore",
    "assess_visual_card_identity_review_readiness",
    "load_identity_review_batch",
    "load_visual_card_identity_review_batch",
    "prepare_visual_card_identity_review_batch",
    "preview_visual_card_identity_review_batch",
]
