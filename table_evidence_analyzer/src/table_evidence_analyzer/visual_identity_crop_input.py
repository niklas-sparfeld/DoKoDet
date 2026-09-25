"""Frozen crop-input contracts for visual identity runs.

This module freezes the geometry source independently from the crop policy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from table_evidence_analyzer.pipeline_data import (
    VISIBLE_CARD_SIDES,
    PipelineDataError,
    PipelineGeometry,
    VisibleCardFrameIdentity,
    canonical_json_bytes,
    parse_pipeline_geometry,
)

VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION = "visual-identity-crop-input/v1"
VISUAL_IDENTITY_CROP_INPUT_KINDS = frozenset(
    {"gemini_polygon", "rfdetr_segment", "reviewed_virtual_card"}
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

CropInputKind = Literal["gemini_polygon", "rfdetr_segment", "reviewed_virtual_card"]
CropInputFailurePhase = Literal["pre_queue", "per_item"]

# A generic policy is allowed to resolve to the item's geometry-specific policy.  The
# resolver must retain that resolved policy on each outcome in M1.
CROP_POLICY_GEOMETRY_KINDS: dict[str, frozenset[str]] = {
    "raw_rectangular": frozenset(
        {"detector-box/v1", "visible-region/v1", "reviewed-visible-region/v1"}
    ),
    "generated_other_region_exclusion": frozenset({"detector-box/v1"}),
    "reviewed_other_region_exclusion": frozenset({"detector-box/v1"}),
    "predicted_visible_region": frozenset({"visible-region/v1"}),
    "predicted_region_with_other_exclusion": frozenset({"visible-region/v1"}),
    "oracle_visible_region": frozenset({"reviewed-visible-region/v1"}),
}

PRE_QUEUE_FAILURE_REASONS = frozenset(
    {
        "missing_input",
        "mixed_recording",
        "changed_source_bytes",
        "stale_scene_derivation",
        "invalid_calibration",
        "duplicate_card_id",
        "invalid_geometry",
        "incomplete_lineage",
    }
)
PER_ITEM_FAILURE_REASONS = frozenset(
    {
        "missing_frame",
        "crop_resolution_error",
        "identity_unusable",
        "face_down",
    }
)


class VisualIdentityCropInputError(PipelineDataError):
    """Raised when a frozen visual-identity crop input is invalid."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise VisualIdentityCropInputError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise VisualIdentityCropInputError(f"{field} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise VisualIdentityCropInputError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise VisualIdentityCropInputError(f"{field} must be a safe identifier")
    return result


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if _DIGEST.fullmatch(result) is None:
        raise VisualIdentityCropInputError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisualIdentityCropInputError(f"{field} must be a positive integer")
    return value


def _failure_tags(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise VisualIdentityCropInputError(f"{field} must be a list of non-empty strings")
    tags = tuple(value)
    if len(set(tags)) != len(tags):
        raise VisualIdentityCropInputError(f"{field} must contain unique values")
    return tags


def _sha256_mapping(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewedVirtualCardLineage:
    """Lineage required when reviewed virtual-card geometry is selected."""

    card_scene_revision_id: str
    card_scene_digest: str
    calibration_revision_id: str
    calibration_digest: str
    scene_derivation_receipt_digest: str
    derived_visible_region_digest: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "virtual_card_lineage"
    ) -> "ReviewedVirtualCardLineage":
        data = _mapping(raw, context)
        fields = {
            "card_scene_revision_id",
            "card_scene_digest",
            "calibration_revision_id",
            "calibration_digest",
            "scene_derivation_receipt_digest",
            "derived_visible_region_digest",
        }
        _strict(data, fields, context)
        return cls(
            card_scene_revision_id=_identifier(
                data["card_scene_revision_id"], f"{context}.card_scene_revision_id"
            ),
            card_scene_digest=_digest(data["card_scene_digest"], f"{context}.card_scene_digest"),
            calibration_revision_id=_identifier(
                data["calibration_revision_id"], f"{context}.calibration_revision_id"
            ),
            calibration_digest=_digest(data["calibration_digest"], f"{context}.calibration_digest"),
            scene_derivation_receipt_digest=_digest(
                data["scene_derivation_receipt_digest"],
                f"{context}.scene_derivation_receipt_digest",
            ),
            derived_visible_region_digest=_digest(
                data["derived_visible_region_digest"],
                f"{context}.derived_visible_region_digest",
            ),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "card_scene_revision_id": self.card_scene_revision_id,
            "card_scene_digest": self.card_scene_digest,
            "calibration_revision_id": self.calibration_revision_id,
            "calibration_digest": self.calibration_digest,
            "scene_derivation_receipt_digest": self.scene_derivation_receipt_digest,
            "derived_visible_region_digest": self.derived_visible_region_digest,
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityCropInputItem:
    """One ordered frame/card geometry item supplied to identity classification."""

    card_id: str
    frame_identity: VisibleCardFrameIdentity
    geometry: PipelineGeometry
    side: Literal["face_up", "face_down", "unknown"]
    identity_usable: bool
    failure_tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "crop_input.items[0]"
    ) -> "VisualIdentityCropInputItem":
        data = _mapping(raw, context)
        _strict(
            data,
            {"card_id", "frame_identity", "geometry", "side", "identity_usable", "failure_tags"},
            context,
        )
        side = data["side"]
        if side not in VISIBLE_CARD_SIDES:
            raise VisualIdentityCropInputError(f"{context}.side is unsupported")
        identity_usable = data["identity_usable"]
        if not isinstance(identity_usable, bool):
            raise VisualIdentityCropInputError(f"{context}.identity_usable must be a boolean")
        return cls(
            card_id=_identifier(data["card_id"], f"{context}.card_id"),
            frame_identity=VisibleCardFrameIdentity.from_mapping(
                _mapping(data["frame_identity"], f"{context}.frame_identity")
            ),
            geometry=parse_pipeline_geometry(
                _mapping(data["geometry"], f"{context}.geometry"), f"{context}.geometry"
            ),
            side=side,
            identity_usable=identity_usable,
            failure_tags=_failure_tags(data["failure_tags"], f"{context}.failure_tags"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "frame_identity": self.frame_identity.to_mapping(),
            "geometry": self.geometry.to_mapping(),
            "side": self.side,
            "identity_usable": self.identity_usable,
            "failure_tags": list(self.failure_tags),
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityCropInput:
    """One immutable geometry input for a visual identity run."""

    input_kind: CropInputKind
    recording_id: str
    accepted_video_sha256: str
    accepted_video_byte_length: int
    source_revision_id: str
    source_revision_digest: str
    source_view_digest: str
    items: tuple[VisualIdentityCropInputItem, ...]
    virtual_card_lineage: ReviewedVirtualCardLineage | None = None
    manifest_digest: str | None = None

    def __post_init__(self) -> None:
        if self.input_kind not in VISUAL_IDENTITY_CROP_INPUT_KINDS:
            raise VisualIdentityCropInputError("input_kind is unsupported")
        _identifier(self.recording_id, "recording_id")
        _digest(self.accepted_video_sha256, "accepted_video_sha256")
        _positive_int(self.accepted_video_byte_length, "accepted_video_byte_length")
        _identifier(self.source_revision_id, "source_revision_id")
        _digest(self.source_revision_digest, "source_revision_digest")
        _digest(self.source_view_digest, "source_view_digest")
        if not self.items:
            raise VisualIdentityCropInputError("items must not be empty")
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, VisualIdentityCropInputItem) for item in self.items
        ):
            raise VisualIdentityCropInputError("items must contain crop-input items")
        if any(
            item.frame_identity.source_video_sha256 != self.accepted_video_sha256
            for item in self.items
        ):
            raise VisualIdentityCropInputError("items must use the accepted recording video bytes")
        keys = [(item.frame_identity.frame_index, item.card_id) for item in self.items]
        if keys != sorted(keys):
            raise VisualIdentityCropInputError("items must be ordered by frame index and card ID")
        if len(keys) != len(set(keys)):
            raise VisualIdentityCropInputError("items must not contain duplicate frame/card IDs")
        if self.input_kind == "reviewed_virtual_card" and self.virtual_card_lineage is None:
            raise VisualIdentityCropInputError(
                "reviewed_virtual_card input needs virtual-card lineage"
            )
        expected_geometry_kind = (
            "reviewed-visible-region/v1"
            if self.input_kind == "reviewed_virtual_card"
            else "visible-region/v1"
        )
        if any(
            item.geometry.to_mapping().get("kind") != expected_geometry_kind for item in self.items
        ):
            raise VisualIdentityCropInputError(f"{self.input_kind} input has incompatible geometry")
        if self.input_kind != "reviewed_virtual_card" and self.virtual_card_lineage is not None:
            raise VisualIdentityCropInputError(
                "generated crop inputs cannot carry virtual-card lineage"
            )
        if self.manifest_digest is not None:
            _digest(self.manifest_digest, "manifest_digest")
            expected = _sha256_mapping(self._manifest_mapping())
            if self.manifest_digest != expected:
                raise VisualIdentityCropInputError("manifest_digest does not match input manifest")

    def _manifest_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION,
            "input_kind": self.input_kind,
            "recording_id": self.recording_id,
            "accepted_video_sha256": self.accepted_video_sha256,
            "accepted_video_byte_length": self.accepted_video_byte_length,
            "source_revision_id": self.source_revision_id,
            "source_revision_digest": self.source_revision_digest,
            "source_view_digest": self.source_view_digest,
            "items": [item.to_mapping() for item in self.items],
            "virtual_card_lineage": (
                None
                if self.virtual_card_lineage is None
                else self.virtual_card_lineage.to_mapping()
            ),
        }
        return value

    @property
    def computed_manifest_digest(self) -> str:
        return _sha256_mapping(self._manifest_mapping())

    def to_mapping(self) -> dict[str, Any]:
        value = self._manifest_mapping()
        value["manifest_digest"] = self.computed_manifest_digest
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisualIdentityCropInput":
        data = _mapping(raw, "crop_input")
        _strict(
            data,
            {
                "schema_version",
                "input_kind",
                "recording_id",
                "accepted_video_sha256",
                "accepted_video_byte_length",
                "source_revision_id",
                "source_revision_digest",
                "source_view_digest",
                "items",
                "virtual_card_lineage",
                "manifest_digest",
            },
            "crop_input",
        )
        if data["schema_version"] != VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION:
            raise VisualIdentityCropInputError("crop_input.schema_version is unsupported")
        kind = data["input_kind"]
        if kind not in VISUAL_IDENTITY_CROP_INPUT_KINDS:
            raise VisualIdentityCropInputError("crop_input.input_kind is unsupported")
        raw_items = data["items"]
        if not isinstance(raw_items, list):
            raise VisualIdentityCropInputError("crop_input.items must be a list")
        lineage = data["virtual_card_lineage"]
        return cls(
            input_kind=kind,
            recording_id=_identifier(data["recording_id"], "crop_input.recording_id"),
            accepted_video_sha256=_digest(
                data["accepted_video_sha256"], "crop_input.accepted_video_sha256"
            ),
            accepted_video_byte_length=_positive_int(
                data["accepted_video_byte_length"], "crop_input.accepted_video_byte_length"
            ),
            source_revision_id=_identifier(
                data["source_revision_id"], "crop_input.source_revision_id"
            ),
            source_revision_digest=_digest(
                data["source_revision_digest"], "crop_input.source_revision_digest"
            ),
            source_view_digest=_digest(data["source_view_digest"], "crop_input.source_view_digest"),
            items=tuple(
                VisualIdentityCropInputItem.from_mapping(item, f"crop_input.items[{index}]")
                for index, item in enumerate(raw_items)
            ),
            virtual_card_lineage=(
                None
                if lineage is None
                else ReviewedVirtualCardLineage.from_mapping(
                    _mapping(lineage, "crop_input.virtual_card_lineage")
                )
            ),
            manifest_digest=_digest(data["manifest_digest"], "crop_input.manifest_digest"),
        )


def validate_crop_policy_compatibility(
    input_value: VisualIdentityCropInput, crop_policy: str
) -> None:
    """Reject a crop policy that cannot represent any selected input geometry."""

    policy = _identifier(crop_policy, "crop_policy")
    supported = CROP_POLICY_GEOMETRY_KINDS.get(policy)
    if supported is None:
        raise VisualIdentityCropInputError(f"crop policy is unsupported: {policy}")
    if any(
        input_item.geometry.to_mapping()["kind"] not in supported
        for input_item in input_value.items
    ):
        raise VisualIdentityCropInputError(
            f"crop policy {policy} is incompatible with selected input geometry"
        )


def canonical_visual_identity_crop_input_bytes(
    value: VisualIdentityCropInput | Mapping[str, Any],
) -> bytes:
    """Serialize one crop input with a stable manifest digest."""

    input_value = (
        value
        if isinstance(value, VisualIdentityCropInput)
        else VisualIdentityCropInput.from_mapping(value)
    )
    return canonical_json_bytes(input_value.to_mapping())


def parse_visual_identity_crop_input_bytes(raw: bytes) -> VisualIdentityCropInput:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualIdentityCropInputError("crop input must be valid UTF-8 JSON") from error
    return VisualIdentityCropInput.from_mapping(_mapping(value, "crop_input"))


__all__ = [
    "CROP_POLICY_GEOMETRY_KINDS",
    "PER_ITEM_FAILURE_REASONS",
    "PRE_QUEUE_FAILURE_REASONS",
    "ReviewedVirtualCardLineage",
    "VISUAL_IDENTITY_CROP_INPUT_KINDS",
    "VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION",
    "VisualIdentityCropInput",
    "VisualIdentityCropInputError",
    "VisualIdentityCropInputItem",
    "canonical_visual_identity_crop_input_bytes",
    "parse_visual_identity_crop_input_bytes",
    "validate_crop_policy_compatibility",
]
