"""Versioned lifecycle receipts for source-video ingestion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath
from typing import Any
from uuid import uuid4

from .data_contract import (
    canonical_json,
    sha256_bytes,
)

LIFECYCLE_RECEIPT_SCHEMA_VERSION = "lifecycle-receipt/v1"
LIFECYCLE_RECEIPT_TYPES = frozenset(
    {
        "source_import",
    }
)
LIFECYCLE_REFERENCE_KINDS = frozenset(
    {
        "source_asset",
        "evidence_package",
        "recording",
        "frame",
        "annotation_set",
        "review",
        "dataset_version",
        "split_version",
        "derived_artifact",
        "training_run",
        "model_bundle",
        "ingestion_manifest",
        "ingestion_index",
        "source_catalog",
    }
)


class LifecycleReceiptError(ValueError):
    """Raised when a lifecycle receipt is invalid."""


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleReceiptError(f"{field_name} must be a non-empty identifier.")
    if value in {".", ".."} or PurePath(value).is_absolute() or "/" in value or "\\" in value:
        raise LifecycleReceiptError(f"{field_name} must not be a local path.")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleReceiptError(f"{field_name} must be a lower-case SHA-256 digest.")
    if any(character not in "0123456789abcdef" for character in value):
        raise LifecycleReceiptError(f"{field_name} must be a lower-case SHA-256 digest.")
    return value


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleReceiptError(f"{field_name} must be a non-empty string.")
    return value


def _utc_timestamp(value: Any, field_name: str) -> str:
    result = _required_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleReceiptError(f"{field_name} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise LifecycleReceiptError(f"{field_name} must use UTC.")
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _strict_fields(data: Mapping[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise LifecycleReceiptError(f"{context} has invalid fields ({'; '.join(parts)}).")


@dataclass(frozen=True, slots=True)
class LifecycleReference:
    """One immutable or versioned object named by a lifecycle receipt."""

    kind: str
    id: str
    digest: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in LIFECYCLE_REFERENCE_KINDS:
            raise LifecycleReceiptError(f"Unknown lifecycle reference kind: {self.kind}.")
        _identifier(self.id, "lifecycle reference id")
        if self.digest is not None:
            _digest(self.digest, "lifecycle reference digest")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LifecycleReference":
        if not isinstance(data, Mapping):
            raise LifecycleReceiptError("Lifecycle reference must be an object.")
        missing = {"kind", "id"} - set(data)
        unknown = set(data) - {"kind", "id", "digest"}
        if missing or unknown:
            parts: list[str] = []
            if missing:
                parts.append(f"missing fields: {', '.join(sorted(missing))}")
            if unknown:
                parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
            raise LifecycleReceiptError(
                f"lifecycle reference has invalid fields ({'; '.join(parts)})."
            )
        return cls(
            kind=_required_string(data["kind"], "lifecycle reference kind"),
            id=_identifier(data["id"], "lifecycle reference id"),
            digest=(None if data.get("digest") is None else _digest(data["digest"], "digest")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "digest": self.digest}


def _reference(value: LifecycleReference | Mapping[str, Any]) -> LifecycleReference:
    if isinstance(value, LifecycleReference):
        return value
    return LifecycleReference.from_mapping(value)


def _references(
    values: Sequence[LifecycleReference | Mapping[str, Any]], field_name: str
) -> tuple[LifecycleReference, ...]:
    result = tuple(
        sorted(
            (_reference(value) for value in values),
            key=lambda item: (item.kind, item.id),
        )
    )
    ids = [(item.kind, item.id) for item in result]
    if len(ids) != len(set(ids)):
        raise LifecycleReceiptError(f"{field_name} must not contain duplicate references.")
    return result


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    """A content-addressed record of one data lifecycle operation."""

    receipt_id: str
    receipt_type: str
    operator: str
    occurred_at: str
    inputs: tuple[LifecycleReference | Mapping[str, Any], ...] = ()
    outputs: tuple[LifecycleReference | Mapping[str, Any], ...] = ()
    dependencies: tuple[LifecycleReference | Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.receipt_id, "receipt_id")
        if self.receipt_type not in LIFECYCLE_RECEIPT_TYPES:
            raise LifecycleReceiptError(f"Unknown lifecycle receipt type: {self.receipt_type}.")
        _required_string(self.operator, "operator")
        _utc_timestamp(self.occurred_at, "occurred_at")
        object.__setattr__(self, "inputs", _references(self.inputs, "inputs"))
        object.__setattr__(self, "outputs", _references(self.outputs, "outputs"))
        object.__setattr__(self, "dependencies", _references(self.dependencies, "dependencies"))
        if not isinstance(self.metadata, Mapping):
            raise LifecycleReceiptError("metadata must be an object.")
        try:
            json.dumps(self.metadata, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise LifecycleReceiptError("metadata must contain JSON values.") from exc
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def digest(self) -> str:
        """Return the stable digest of receipt contents, excluding identity and time."""

        payload = {
            "schema_version": LIFECYCLE_RECEIPT_SCHEMA_VERSION,
            "receipt_type": self.receipt_type,
            "operator": self.operator,
            "inputs": [item.to_mapping() for item in self.inputs],
            "outputs": [item.to_mapping() for item in self.outputs],
            "dependencies": [item.to_mapping() for item in self.dependencies],
            "metadata": self.metadata,
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": LIFECYCLE_RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "receipt_type": self.receipt_type,
            "operator": self.operator,
            "occurred_at": self.occurred_at,
            "inputs": [item.to_mapping() for item in self.inputs],
            "outputs": [item.to_mapping() for item in self.outputs],
            "dependencies": [item.to_mapping() for item in self.dependencies],
            "metadata": self.metadata,
            "receipt_digest": self.digest,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LifecycleReceipt":
        fields = {
            "schema_version",
            "receipt_id",
            "receipt_type",
            "operator",
            "occurred_at",
            "inputs",
            "outputs",
            "dependencies",
            "metadata",
            "receipt_digest",
        }
        if not isinstance(data, Mapping):
            raise LifecycleReceiptError("Lifecycle receipt must be an object.")
        _strict_fields(data, fields, "lifecycle receipt")
        if data["schema_version"] != LIFECYCLE_RECEIPT_SCHEMA_VERSION:
            raise LifecycleReceiptError(
                f"schema_version must be {LIFECYCLE_RECEIPT_SCHEMA_VERSION}."
            )
        for field_name in ("inputs", "outputs", "dependencies"):
            if not isinstance(data[field_name], list):
                raise LifecycleReceiptError(f"{field_name} must be a list.")
        receipt = cls(
            receipt_id=_identifier(data["receipt_id"], "receipt_id"),
            receipt_type=_required_string(data["receipt_type"], "receipt_type"),
            operator=_required_string(data["operator"], "operator"),
            occurred_at=_utc_timestamp(data["occurred_at"], "occurred_at"),
            inputs=tuple(LifecycleReference.from_mapping(item) for item in data["inputs"]),
            outputs=tuple(LifecycleReference.from_mapping(item) for item in data["outputs"]),
            dependencies=tuple(
                LifecycleReference.from_mapping(item) for item in data["dependencies"]
            ),
            metadata=data["metadata"],
        )
        if receipt.digest != _digest(data["receipt_digest"], "receipt_digest"):
            raise LifecycleReceiptError("receipt_digest does not match the receipt contents.")
        return receipt


def _json_write(path: str | Path, value: Mapping[str, Any], *, overwrite: bool = False) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise LifecycleReceiptError(f"Refusing to overwrite file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def save_lifecycle_receipt(
    receipt: LifecycleReceipt, path: str | Path, *, overwrite: bool = False
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        existing = load_lifecycle_receipt(destination)
        if existing.digest == receipt.digest:
            return destination
    return _json_write(path, receipt.to_mapping(), overwrite=overwrite)


def load_lifecycle_receipt(path: str | Path) -> LifecycleReceipt:
    receipt_path = Path(path)
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and "lifecycle_receipt" in payload:
            payload = payload["lifecycle_receipt"]
        return LifecycleReceipt.from_mapping(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, LifecycleReceiptError):
            raise
        raise LifecycleReceiptError(f"Invalid lifecycle receipt {receipt_path}: {exc}") from exc


def build_source_import_receipt(
    result: Any,
    *,
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create a receipt for immutable source-video ingestion."""

    rows = result.index.get("videos", [])
    source_assets = tuple(
        LifecycleReference("source_asset", row["video_id"], row["sha256"]) for row in rows
    )
    digest = _digest(result.dataset_version_digest, "dataset_version_digest")
    outputs = source_assets + (
        LifecycleReference("ingestion_manifest", f"manifest-{digest}", digest),
        LifecycleReference("ingestion_index", f"index-{digest}", digest),
    )
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="source_import",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=source_assets,
        outputs=outputs,
        dependencies=source_assets,
        metadata={
            "source_count": len(source_assets),
            "dataset_version_digest": digest,
        },
    )


__all__ = [
    "LIFECYCLE_RECEIPT_SCHEMA_VERSION",
    "LIFECYCLE_RECEIPT_TYPES",
    "LIFECYCLE_REFERENCE_KINDS",
    "LifecycleReceipt",
    "LifecycleReceiptError",
    "LifecycleReference",
    "build_source_import_receipt",
    "load_lifecycle_receipt",
    "save_lifecycle_receipt",
]
