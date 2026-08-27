"""Versioned lifecycle receipts and source-retirement impact tracking."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath
from typing import Any
from uuid import uuid4

from .data_contract import (
    SOURCE_RECORD_SCHEMA_VERSION,
    DatasetVersion,
    SourceRecord,
    canonical_json,
    sha256_bytes,
)

LIFECYCLE_RECEIPT_SCHEMA_VERSION = "lifecycle-receipt/v1"
LIFECYCLE_RECEIPT_TYPES = frozenset(
    {
        "source_import",
        "evidence_import",
        "annotation_application",
        "dataset_creation",
        "split_creation",
        "training_run",
        "retirement",
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
_IMPACT_REFERENCE_KINDS = (
    "evidence_package",
    "annotation_set",
    "review",
    "dataset_version",
    "split_version",
    "derived_artifact",
    "training_run",
    "model_bundle",
    "ingestion_manifest",
    "ingestion_index",
)


class LifecycleReceiptError(ValueError):
    """Raised when a lifecycle receipt or retirement operation is invalid."""


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


def load_lifecycle_receipts(path: str | Path) -> tuple[LifecycleReceipt, ...]:
    """Load lifecycle receipts from one file or a directory.

    Unrelated JSON artifacts are ignored. A lifecycle receipt, including a nested receipt in the
    table-observation apply artifact, is strict and must validate.
    """

    receipt_path = Path(path)
    paths = [receipt_path] if receipt_path.is_file() else sorted(receipt_path.glob("*.json"))
    receipts: list[LifecycleReceipt] = []
    for candidate in paths:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LifecycleReceiptError(
                f"Could not read lifecycle receipt {candidate}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            continue
        if payload.get("schema_version") == LIFECYCLE_RECEIPT_SCHEMA_VERSION:
            receipts.append(LifecycleReceipt.from_mapping(payload))
        elif isinstance(payload.get("lifecycle_receipt"), Mapping):
            receipts.append(LifecycleReceipt.from_mapping(payload["lifecycle_receipt"]))
    ids = [receipt.receipt_id for receipt in receipts]
    if len(ids) != len(set(ids)):
        raise LifecycleReceiptError("Lifecycle receipt IDs must be unique.")
    return tuple(sorted(receipts, key=lambda receipt: receipt.receipt_id))


def _source_reference(source: SourceRecord) -> LifecycleReference:
    return LifecycleReference("source_asset", source.source_asset_id, source.sha256)


def _annotation_reference(annotation: Any, *, reviewed: bool = False) -> LifecycleReference:
    from .vision_annotation import annotation_bytes

    value = annotation
    if reviewed and hasattr(annotation, "reviewed_annotation"):
        value = annotation.reviewed_annotation
    return LifecycleReference(
        "annotation_set",
        value.annotation_set_id,
        sha256_bytes(annotation_bytes(value)),
    )


def _review_reference(review: Any) -> LifecycleReference:
    return LifecycleReference(
        "review",
        review.review_id,
        sha256_bytes(canonical_json(review.to_mapping()).encode("utf-8")),
    )


def _review_values(reviews: Any) -> tuple[Any, ...]:
    if reviews is None:
        return ()
    if isinstance(reviews, Mapping):
        return tuple(reviews.values())
    return tuple(reviews)


def _dataset_from_result(dataset_or_result: Any) -> DatasetVersion:
    dataset = getattr(dataset_or_result, "dataset_version", dataset_or_result)
    if not isinstance(dataset, DatasetVersion):
        raise LifecycleReceiptError("A dataset version or dataset assembly result is required.")
    return dataset


def _dataset_dependencies(
    dataset: DatasetVersion,
    *,
    sources: Sequence[SourceRecord] = (),
    reviewed_annotations: Sequence[Any] = (),
    reviews: Any = None,
) -> tuple[LifecycleReference, ...]:
    source_by_id = {source.source_asset_id: source for source in sources}
    annotations_by_id = {
        annotation.annotation_set_id: annotation for annotation in reviewed_annotations
    }
    reviews_by_id = {review.review_id: review for review in _review_values(reviews)}
    references: list[LifecycleReference] = []
    for entry in dataset.entries:
        source = source_by_id.get(entry.source_asset_id)
        references.append(
            _source_reference(source)
            if source is not None
            else LifecycleReference("source_asset", entry.source_asset_id, entry.source_sha256)
        )
        annotation = annotations_by_id.get(entry.annotation_set_id)
        if annotation is not None:
            references.append(_annotation_reference(annotation))
        else:
            references.append(LifecycleReference("annotation_set", entry.annotation_set_id))
        review = reviews_by_id.get(entry.review_id)
        references.append(
            _review_reference(review)
            if review is not None
            else LifecycleReference("review", entry.review_id)
        )
    return _references(references, "dataset dependencies")


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


def _manifest_file(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate / "manifest.json" if candidate.is_dir() else candidate


def build_evidence_import_receipt(
    annotations: Sequence[Any],
    *,
    manifests: Sequence[str | Path] = (),
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create a receipt for evidence-package import into draft annotations."""

    from .vision_annotation import annotation_bytes

    outputs = tuple(
        LifecycleReference(
            "annotation_set",
            annotation.annotation_set_id,
            sha256_bytes(annotation_bytes(annotation)),
        )
        for annotation in annotations
    )
    package_refs: list[LifecycleReference] = []
    for annotation in annotations:
        package_id = annotation.source.package_id
        if package_id is None:
            continue
        matching_manifest = next(
            (
                _manifest_file(path)
                for path in manifests
                if _manifest_file(path).is_file()
                and json.loads(_manifest_file(path).read_text(encoding="utf-8")).get("package_id")
                == package_id
            ),
            None,
        )
        package_refs.append(
            LifecycleReference(
                "evidence_package",
                package_id,
                _file_digest(matching_manifest) if matching_manifest is not None else None,
            )
        )
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="evidence_import",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=tuple(package_refs),
        outputs=outputs,
        dependencies=tuple(package_refs) + outputs,
        metadata={"annotation_count": len(outputs), "draft_annotations": True},
    )


def _file_digest(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise LifecycleReceiptError(f"Could not read receipt input {path}: {exc}") from exc


def build_annotation_application_receipt(
    *,
    annotation_set_id: str,
    review_id: str,
    source_annotation_digest: str,
    output_annotation_digest: str,
    review_digest: str,
    event_decision: str,
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create the standard receipt nested in a table-observation apply artifact."""

    annotation_before = LifecycleReference(
        "annotation_set",
        annotation_set_id,
        _digest(source_annotation_digest, "source_annotation_digest"),
    )
    annotation_after = LifecycleReference(
        "annotation_set",
        annotation_set_id,
        _digest(output_annotation_digest, "output_annotation_digest"),
    )
    review = LifecycleReference(
        "review",
        _identifier(review_id, "review_id"),
        _digest(review_digest, "review_digest"),
    )
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="annotation_application",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=(annotation_before, review),
        outputs=(annotation_after,),
        dependencies=(annotation_before, review),
        metadata={"annotation_set_id": annotation_set_id, "event_decision": event_decision},
    )


def build_dataset_creation_receipt(
    dataset_or_result: Any,
    *,
    sources: Sequence[SourceRecord] = (),
    reviewed_annotations: Sequence[Any] = (),
    reviews: Any = None,
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create a receipt naming every source and reviewed label version in a dataset."""

    dataset = _dataset_from_result(dataset_or_result)
    dependencies = _dataset_dependencies(
        dataset,
        sources=sources,
        reviewed_annotations=reviewed_annotations,
        reviews=reviews,
    )
    dataset_ref = LifecycleReference("dataset_version", dataset.dataset_version_id, dataset.digest)
    result = getattr(dataset_or_result, "unassigned", ())
    excluded = getattr(dataset_or_result, "excluded", ())
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="dataset_creation",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=dependencies,
        outputs=(dataset_ref,),
        dependencies=dependencies,
        metadata={
            "dataset_version_id": dataset.dataset_version_id,
            "dataset_version_digest": dataset.digest,
            "entry_count": len(dataset.entries),
            "unassigned_count": len(result),
            "excluded_count": len(excluded),
        },
    )


def build_split_creation_receipt(
    dataset: DatasetVersion,
    split: Any,
    *,
    sources: Sequence[SourceRecord] = (),
    reviewed_annotations: Sequence[Any] = (),
    reviews: Any = None,
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create a receipt for a split bound to one frozen dataset digest."""

    try:
        split.validate_against(dataset)
    except (AttributeError, ValueError) as exc:
        raise LifecycleReceiptError(f"Split does not validate against its dataset: {exc}") from exc
    dataset_ref = LifecycleReference("dataset_version", dataset.dataset_version_id, dataset.digest)
    split_ref = LifecycleReference("split_version", split.split_version_id, split.digest)
    dependencies = _dataset_dependencies(
        dataset,
        sources=sources,
        reviewed_annotations=reviewed_annotations,
        reviews=reviews,
    )
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="split_creation",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=(dataset_ref,) + dependencies,
        outputs=(split_ref,),
        dependencies=(dataset_ref,) + dependencies,
        metadata={
            "dataset_version_id": dataset.dataset_version_id,
            "dataset_version_digest": dataset.digest,
            "split_version_id": split.split_version_id,
            "split_version_digest": split.digest,
        },
    )


def _derived_references(
    values: Sequence[str | Mapping[str, Any] | LifecycleReference], kind: str
) -> tuple[LifecycleReference, ...]:
    result: list[LifecycleReference] = []
    for value in values:
        if isinstance(value, LifecycleReference):
            result.append(value)
        elif isinstance(value, Mapping):
            result.append(LifecycleReference.from_mapping(value))
        else:
            result.append(LifecycleReference(kind, _identifier(value, f"{kind}_id")))
    return _references(result, f"{kind} references")


def build_training_run_receipt(
    dataset: DatasetVersion,
    split: Any | None,
    *,
    training_run_id: str,
    operator: str,
    model_bundle_id: str | None = None,
    derived_artifact_ids: Sequence[str | Mapping[str, Any] | LifecycleReference] = (),
    sources: Sequence[SourceRecord] = (),
    reviewed_annotations: Sequence[Any] = (),
    reviews: Any = None,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create run provenance that expands to every source and label version used."""

    dataset_ref = LifecycleReference("dataset_version", dataset.dataset_version_id, dataset.digest)
    split_refs: tuple[LifecycleReference, ...] = ()
    if split is not None:
        try:
            split.validate_against(dataset)
        except (AttributeError, ValueError) as exc:
            raise LifecycleReceiptError(
                f"Split does not validate against its dataset: {exc}"
            ) from exc
        split_refs = (LifecycleReference("split_version", split.split_version_id, split.digest),)
    dependencies = _dataset_dependencies(
        dataset,
        sources=sources,
        reviewed_annotations=reviewed_annotations,
        reviews=reviews,
    )
    run_ref = LifecycleReference("training_run", _identifier(training_run_id, "training_run_id"))
    outputs: tuple[LifecycleReference, ...] = (run_ref,)
    if model_bundle_id is not None:
        outputs += (
            LifecycleReference("model_bundle", _identifier(model_bundle_id, "model_bundle_id")),
        )
    outputs += _derived_references(derived_artifact_ids, "derived_artifact")
    version_dependencies = (dataset_ref,) + split_refs + dependencies
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="training_run",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=version_dependencies,
        outputs=outputs,
        dependencies=version_dependencies,
        metadata={
            "dataset_version_id": dataset.dataset_version_id,
            "dataset_version_digest": dataset.digest,
            "split_version_id": split.split_version_id if split is not None else None,
            "source_count": len({entry.source_asset_id for entry in dataset.entries}),
            "annotation_set_count": len({entry.annotation_set_id for entry in dataset.entries}),
        },
    )


def _receipt_values(
    receipts: Sequence[LifecycleReceipt] | str | Path | None,
) -> tuple[LifecycleReceipt, ...]:
    if receipts is None:
        return ()
    if isinstance(receipts, (str, Path)):
        return load_lifecycle_receipts(receipts)
    return tuple(receipts)


def find_source_impact(
    source_asset_ids: Sequence[str],
    receipts: Sequence[LifecycleReceipt] | str | Path | None = None,
) -> dict[str, list[str]]:
    """Find versioned artifacts and runs affected by source withdrawal.

    The search follows receipt references transitively. A training receipt is therefore found even
    when an intermediate split receipt is the only link between the run and the source.
    """

    source_ids = {_identifier(value, "source_asset_id") for value in source_asset_ids}
    if not source_ids:
        raise LifecycleReceiptError("At least one source_asset_id is required.")
    receipt_values = _receipt_values(receipts)
    affected: set[tuple[str, str]] = {("source_asset", value) for value in source_ids}
    matched_receipts: set[str] = set()
    changed = True
    while changed:
        changed = False
        for receipt in receipt_values:
            refs = receipt.inputs + receipt.outputs + receipt.dependencies
            if not any((reference.kind, reference.id) in affected for reference in refs):
                continue
            if receipt.receipt_id not in matched_receipts:
                matched_receipts.add(receipt.receipt_id)
                changed = True
            for reference in refs:
                token = (reference.kind, reference.id)
                if token not in affected:
                    affected.add(token)
                    changed = True
    result: dict[str, list[str]] = {f"affected_{kind}s": [] for kind in _IMPACT_REFERENCE_KINDS}
    for kind, identifier in sorted(affected):
        if kind in _IMPACT_REFERENCE_KINDS:
            result[f"affected_{kind}s"].append(identifier)
    result["affected_receipts"] = sorted(matched_receipts)
    result["source_assets"] = sorted(source_ids)
    return result


def build_retirement_receipt(
    source_assets: Sequence[SourceRecord],
    *,
    source_asset_ids: Sequence[str],
    retention_state: str,
    reason: str,
    impact: Mapping[str, Any],
    source_catalog_id: str,
    source_catalog_digest: str,
    operator: str,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> LifecycleReceipt:
    """Create a receipt for a new source-catalog state and its dependency impact."""

    if retention_state not in {"deletion_requested", "retired"}:
        raise LifecycleReceiptError(
            "retention_state must be deletion_requested or retired for retirement."
        )
    _required_string(reason, "reason")
    selected_ids = {_identifier(value, "source_asset_id") for value in source_asset_ids}
    selected = [source for source in source_assets if source.source_asset_id in selected_ids]
    if len(selected) != len(selected_ids):
        raise LifecycleReceiptError("Retirement names an unknown source asset.")
    source_refs = tuple(_source_reference(source) for source in selected)
    catalog_ref = LifecycleReference(
        "source_catalog",
        _identifier(source_catalog_id, "source_catalog_id"),
        _digest(source_catalog_digest, "source_catalog_digest"),
    )
    return LifecycleReceipt(
        receipt_id=receipt_id or f"receipt-{uuid4().hex}",
        receipt_type="retirement",
        operator=operator,
        occurred_at=occurred_at or _now(),
        inputs=source_refs,
        outputs=(catalog_ref,),
        dependencies=source_refs,
        metadata={
            "source_asset_ids": sorted(selected_ids),
            "retention_state": retention_state,
            "reason": reason,
            "impact": dict(impact),
        },
    )


@dataclass(frozen=True, slots=True)
class SourceRetirementResult:
    source_records: tuple[SourceRecord, ...]
    impact: Mapping[str, list[str]]
    receipt: LifecycleReceipt


def retire_source_records(
    sources: Sequence[SourceRecord],
    *,
    source_asset_ids: Sequence[str],
    operator: str,
    reason: str,
    retention_state: str = "retired",
    receipts: Sequence[LifecycleReceipt] | str | Path | None = None,
    receipt_id: str | None = None,
    occurred_at: str | None = None,
) -> SourceRetirementResult:
    """Return a new source catalog state without touching immutable source bytes."""

    source_values = tuple(sources)
    if len({source.source_asset_id for source in source_values}) != len(source_values):
        raise LifecycleReceiptError("source_asset_id values must be unique.")
    selected_ids = {_identifier(value, "source_asset_id") for value in source_asset_ids}
    source_by_id = {source.source_asset_id: source for source in source_values}
    if not selected_ids or not selected_ids <= set(source_by_id):
        raise LifecycleReceiptError("Retirement names an unknown or empty source asset set.")
    updated = tuple(
        sorted(
            (
                replace(source, retention_state=retention_state)
                if source.source_asset_id in selected_ids
                else source
                for source in source_values
            ),
            key=lambda source: source.source_asset_id,
        )
    )
    catalog_payload = {
        "schema_version": SOURCE_RECORD_SCHEMA_VERSION,
        "sources": [source.to_mapping() for source in updated],
    }
    catalog_digest = sha256_bytes(canonical_json(catalog_payload).encode("utf-8"))
    impact = find_source_impact(sorted(selected_ids), receipts)
    receipt = build_retirement_receipt(
        source_values,
        source_asset_ids=sorted(selected_ids),
        retention_state=retention_state,
        reason=reason,
        impact=impact,
        source_catalog_id=f"source-catalog-{catalog_digest[:16]}",
        source_catalog_digest=catalog_digest,
        operator=operator,
        receipt_id=receipt_id,
        occurred_at=occurred_at,
    )
    return SourceRetirementResult(updated, impact, receipt)


def save_source_records(
    sources: Sequence[SourceRecord], path: str | Path, *, overwrite: bool = False
) -> Path:
    values = tuple(sorted(sources, key=lambda source: source.source_asset_id))
    if not values:
        raise LifecycleReceiptError("At least one source record is required.")
    return _json_write(
        path,
        {
            "schema_version": SOURCE_RECORD_SCHEMA_VERSION,
            "sources": [source.to_mapping() for source in values],
        },
        overwrite=overwrite,
    )


__all__ = [
    "LIFECYCLE_RECEIPT_SCHEMA_VERSION",
    "LIFECYCLE_RECEIPT_TYPES",
    "LIFECYCLE_REFERENCE_KINDS",
    "LifecycleReceipt",
    "LifecycleReceiptError",
    "LifecycleReference",
    "SourceRetirementResult",
    "build_annotation_application_receipt",
    "build_dataset_creation_receipt",
    "build_evidence_import_receipt",
    "build_retirement_receipt",
    "build_source_import_receipt",
    "build_split_creation_receipt",
    "build_training_run_receipt",
    "find_source_impact",
    "load_lifecycle_receipt",
    "load_lifecycle_receipts",
    "retire_source_records",
    "save_lifecycle_receipt",
    "save_source_records",
]
