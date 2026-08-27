"""Dataset assembly, group-safe splits, validation, and coverage for table observations."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data_contract import (
    DatasetEntry,
    DatasetVersion,
    Eligibility,
    EntityRef,
    LineageGraph,
    SourceRecord,
    canonical_json,
    sha256_bytes,
)
from .vision_annotation import (
    TABLE_OBSERVATION_SCHEMA_VERSION,
    TableObservationAnnotation,
    VisionAnnotationError,
    annotation_bytes,
    load_table_observation_annotation,
)

TABLE_EVIDENCE_DATASET_TASK = "table_evidence_analyzer_identity_crop"
TABLE_DATASET_SPLIT_SCHEMA_VERSION = "table-dataset-split/v1"
TABLE_DATASET_COVERAGE_SCHEMA_VERSION = "table-dataset-coverage/v1"
DEFAULT_TABLE_DATASET_GROUP_KEYS = (
    "session_id",
    "game_id",
    "table_setup",
    "source_lineage",
)
DEFAULT_TABLE_DATASET_TRANSFORM_VERSION = "identity-crop-v1"
DEFAULT_ALLOWED_USES = ("train", "validation", "test")


class TableDatasetError(ValueError):
    """Raised when a table-observation dataset cannot be made safe."""


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TableDatasetError(f"{field} must be a non-empty identifier.")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise TableDatasetError(f"{field} must not be a local path.")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise TableDatasetError(f"{field} must be a SHA-256 digest.")
    if any(character not in "0123456789abcdef" for character in value):
        raise TableDatasetError(f"{field} must be a lower-case SHA-256 digest.")
    return value


def _json_write(path: str | Path, value: Any, *, overwrite: bool = False) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise TableDatasetError(f"Refusing to overwrite file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def _as_annotations(
    values: Sequence[TableObservationAnnotation | str | Path],
) -> tuple[TableObservationAnnotation, ...]:
    annotations = tuple(
        load_table_observation_annotation(value) if isinstance(value, (str, Path)) else value
        for value in values
    )
    if any(not isinstance(annotation, TableObservationAnnotation) for annotation in annotations):
        raise TableDatasetError(
            "annotations must be table-observation annotation objects or paths."
        )
    ids = [annotation.annotation_set_id for annotation in annotations]
    if len(ids) != len(set(ids)):
        raise TableDatasetError("annotation_set_id values must be unique.")
    return tuple(sorted(annotations, key=lambda annotation: annotation.annotation_set_id))


def load_table_observation_annotations(path: str | Path) -> tuple[TableObservationAnnotation, ...]:
    """Load only table-observation annotations from a directory or one JSON file."""

    annotation_path = Path(path)
    paths = (
        [annotation_path] if annotation_path.is_file() else sorted(annotation_path.glob("*.json"))
    )
    annotations: list[TableObservationAnnotation] = []
    for candidate in paths:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TableDatasetError(f"Could not read annotation {candidate}: {exc}") from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != TABLE_OBSERVATION_SCHEMA_VERSION
        ):
            # A directory can also contain unrelated CardEventNet annotation files or receipts.
            # Those are not part of this contract and are ignored by the explicit loader.
            continue
        try:
            annotations.append(load_table_observation_annotation(candidate))
        except VisionAnnotationError as exc:
            raise TableDatasetError(
                f"Invalid table-observation annotation {candidate}: {exc}"
            ) from exc
    if not annotations:
        raise TableDatasetError(f"No table-observation annotations found at {annotation_path}.")
    return _as_annotations(annotations)


def load_source_records(path: str | Path) -> tuple[SourceRecord, ...]:
    """Load source records from a list or ``{"sources": [...]}`` JSON document."""

    source_path = Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TableDatasetError(f"Could not read source records {source_path}: {exc}") from exc
    if isinstance(payload, Mapping) and "sources" in payload:
        rows = payload["sources"]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = [payload]
    if not isinstance(rows, list):
        raise TableDatasetError("Source records must contain a list of sources.")
    try:
        sources = tuple(SourceRecord.from_mapping(row) for row in rows)
    except (TypeError, KeyError, ValueError) as exc:
        raise TableDatasetError(f"Invalid source records: {exc}") from exc
    if not sources:
        raise TableDatasetError("At least one source record is required.")
    if len({source.source_asset_id for source in sources}) != len(sources):
        raise TableDatasetError("source_asset_id values must be unique.")
    return tuple(sorted(sources, key=lambda source: source.source_asset_id))


def load_source_metadata(path: str | Path) -> dict[str, Mapping[str, Any]]:
    """Load optional human-confirmed coverage metadata keyed by source asset ID."""

    metadata_path = Path(path)
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TableDatasetError(f"Could not read source metadata {metadata_path}: {exc}") from exc
    if isinstance(payload, Mapping) and "sources" in payload:
        payload = payload["sources"]
    if not isinstance(payload, Mapping):
        raise TableDatasetError("Source metadata must be an object keyed by source_asset_id.")
    result: dict[str, Mapping[str, Any]] = {}
    for source_asset_id, value in payload.items():
        if not isinstance(value, Mapping):
            raise TableDatasetError(f"Metadata for {source_asset_id} must be an object.")
        result[_id(source_asset_id, "source_asset_id")] = value
    return result


def load_lineage_graph(path: str | Path) -> LineageGraph:
    lineage_path = Path(path)
    try:
        payload = json.loads(lineage_path.read_text(encoding="utf-8"))
        graph = LineageGraph.from_mapping(payload)
        graph.validate()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise TableDatasetError(f"Invalid lineage graph {lineage_path}: {exc}") from exc
    return graph


def _source_mapping(sources: Sequence[SourceRecord]) -> dict[str, SourceRecord]:
    result: dict[str, SourceRecord] = {}
    for source in sources:
        if source.source_asset_id in result:
            raise TableDatasetError(f"Duplicate source record for {source.source_asset_id}.")
        result[source.source_asset_id] = source
    duplicate_digests: dict[str, list[str]] = {}
    for source in sources:
        duplicate_digests.setdefault(source.sha256, []).append(source.source_asset_id)
    duplicates = [ids for ids in duplicate_digests.values() if len(ids) > 1]
    if duplicates:
        formatted = ", ".join("/".join(sorted(ids)) for ids in sorted(duplicates))
        raise TableDatasetError(
            f"Duplicate source bytes have different source_asset_id values: {formatted}."
        )
    return result


def _review_mapping(reviews: Any) -> dict[str, Any]:
    if reviews is None:
        return {}
    if isinstance(reviews, Mapping):
        values = reviews.items()
    else:
        values = ((getattr(review, "annotation_set_id", ""), review) for review in reviews)
    result: dict[str, Any] = {}
    for annotation_set_id, review in values:
        if isinstance(review, (str, Path)):
            from .vision_review import VisionReviewError, load_table_observation_review

            try:
                review = load_table_observation_review(review)
            except VisionReviewError as exc:
                raise TableDatasetError(
                    f"Invalid table-observation review {review}: {exc}"
                ) from exc
        key = annotation_set_id or getattr(review, "annotation_set_id", None)
        if not key:
            raise TableDatasetError("Each review must identify an annotation set.")
        if key in result:
            raise TableDatasetError(f"Duplicate review for annotation set {key}.")
        result[key] = review
    return result


def load_table_observation_reviews(path: str | Path) -> dict[str, Any]:
    """Load table-observation review artifacts from a directory or one JSON file."""

    review_path = Path(path)
    paths = [review_path] if review_path.is_file() else sorted(review_path.glob("*.json"))
    from .vision_review import VisionReviewError, load_table_observation_review

    reviews: dict[str, Any] = {}
    for candidate in paths:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TableDatasetError(f"Could not read review {candidate}: {exc}") from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != "table-observation-review/v1"
        ):
            continue
        try:
            review = load_table_observation_review(candidate)
        except (VisionReviewError, ValueError) as exc:
            raise TableDatasetError(f"Invalid table-observation review {candidate}: {exc}") from exc
        if review.annotation_set_id in reviews:
            raise TableDatasetError(
                f"Duplicate review for annotation set {review.annotation_set_id}."
            )
        reviews[review.annotation_set_id] = review
    if not reviews:
        raise TableDatasetError(f"No table-observation reviews found at {review_path}.")
    return reviews


def _annotation_source_asset(
    annotation: TableObservationAnnotation,
    sources: Mapping[str, SourceRecord],
    lineage: LineageGraph | None,
) -> str:
    source = annotation.source
    if source.package_id is not None or source.recording_id is not None:
        if lineage is None:
            raise TableDatasetError(
                f"Annotation {annotation.annotation_set_id} needs a lineage graph for its source."
            )
        kind = "evidence_package" if source.package_id is not None else "recording"
        entity_id = source.package_id or source.recording_id
        return lineage.single_source_asset_for(EntityRef(kind, entity_id)).id
    assert source.video_id is not None
    matches = [
        record.source_asset_id for record in sources.values() if record.video_id == source.video_id
    ]
    if len(matches) != 1:
        raise TableDatasetError(
            f"Annotation {annotation.annotation_set_id} video_id {source.video_id} does not "
            "resolve to one source."
        )
    return matches[0]


def _assert_frame_lineage(
    annotation: TableObservationAnnotation,
    source_asset_id: str,
    lineage: LineageGraph | None,
) -> None:
    if lineage is None:
        raise TableDatasetError(
            f"Annotation {annotation.annotation_set_id} needs a lineage graph for frame samples."
        )
    for card in annotation.observed_cards:
        for frame in card.frame_observations:
            resolved = lineage.single_source_asset_for(EntityRef("frame", frame.frame_id)).id
            if resolved != source_asset_id:
                raise TableDatasetError(
                    f"Frame {frame.frame_id} does not share source lineage with annotation "
                    f"{annotation.annotation_set_id}."
                )
    if annotation.source.package_id is not None:
        edge_exists = any(
            edge.relation == "annotation_for_evidence_package"
            and edge.parent == EntityRef("evidence_package", annotation.source.package_id)
            and edge.child == EntityRef("annotation_set", annotation.annotation_set_id)
            for edge in lineage.edges
        )
        if not edge_exists:
            raise TableDatasetError(
                f"Annotation {annotation.annotation_set_id} is not linked to its evidence package."
            )


def _group_keys(source: SourceRecord) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [("source_lineage", source.source_asset_id)]
    for name in ("session_id", "game_id", "table_setup"):
        value = getattr(source, name)
        if value is not None:
            values.append((name, value))
    return tuple(sorted(values))


def _reviewed_annotation(
    annotation: TableObservationAnnotation,
    reviews: Mapping[str, Any],
) -> tuple[TableObservationAnnotation | None, str | None]:
    review = reviews.get(annotation.annotation_set_id)
    if review is None:
        if annotation.review_state != "reviewed":
            return None, None
        return annotation, None
    reviewed = getattr(review, "reviewed_annotation", None)
    review_id = getattr(review, "review_id", None)
    if reviewed is None or not review_id:
        raise TableDatasetError(
            f"Review for {annotation.annotation_set_id} is not a table-observation review artifact."
        )
    if reviewed.annotation_set_id != annotation.annotation_set_id:
        raise TableDatasetError("Review annotation_set_id does not match its reviewed annotation.")
    expected_source_hash = sha256_bytes(annotation_bytes(annotation))
    if getattr(review, "source_annotation_sha256", None) != expected_source_hash:
        raise TableDatasetError(
            f"Review for {annotation.annotation_set_id} does not match its source annotation."
        )
    if annotation.review_state == "reviewed" and annotation != reviewed:
        raise TableDatasetError(
            f"Reviewed annotation {annotation.annotation_set_id} does not match its "
            "review snapshot."
        )
    return reviewed, review_id


@dataclass(frozen=True, slots=True)
class DatasetAssemblyResult:
    dataset_version: DatasetVersion
    unassigned: tuple[dict[str, Any], ...]
    excluded: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version.to_mapping(),
            "unassigned": list(self.unassigned),
            "excluded": list(self.excluded),
            "coverage": self.coverage,
        }


def assemble_table_evidence_dataset(
    annotations: Sequence[TableObservationAnnotation | str | Path],
    sources: Sequence[SourceRecord],
    *,
    reviews: Any = None,
    lineage: LineageGraph | None = None,
    dataset_version_id: str = "table-evidence-dataset-v1",
    allowed_use_filter: Sequence[str] = DEFAULT_ALLOWED_USES,
    intended_use: str | None = None,
    task: str = TABLE_EVIDENCE_DATASET_TASK,
    target_schema: str = TABLE_OBSERVATION_SCHEMA_VERSION,
    transform_version: str = DEFAULT_TABLE_DATASET_TRANSFORM_VERSION,
    creation_code_revision: str = "working-tree",
    dirty_state: bool = True,
    deck_design_version: str | None = None,
    card_set_version: str | None = None,
    source_metadata: Mapping[str, Mapping[str, Any] | Any] | None = None,
) -> DatasetAssemblyResult:
    """Build a crop dataset from reviewed, identity-usable table observations.

    Each usable frame observation becomes one explicit sample. False event proposals are retained
    when they contain visible cards; the event decision never becomes a card identity label.
    """

    annotation_values = _as_annotations(annotations)
    source_by_id = _source_mapping(sources)
    review_by_annotation = _review_mapping(reviews)
    if lineage is not None:
        try:
            lineage.validate()
        except ValueError as exc:
            raise TableDatasetError(f"Invalid lineage graph: {exc}") from exc
    allowed = tuple(allowed_use_filter)
    if not allowed or len(set(allowed)) != len(allowed):
        raise TableDatasetError("allowed_use_filter must contain at least one unique use.")
    for use in allowed:
        if use not in {"train", "validation", "test", "evaluation"}:
            raise TableDatasetError(f"Unknown allowed use: {use}.")
    entries: list[DatasetEntry] = []
    reviewed_annotations: list[TableObservationAnnotation] = []
    unassigned: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for annotation in annotation_values:
        try:
            reviewed, review_id = _reviewed_annotation(annotation, review_by_annotation)
            if reviewed is None:
                unassigned.append(
                    {
                        "annotation_set_id": annotation.annotation_set_id,
                        "reason": "annotation_not_reviewed",
                    }
                )
                continue
            if review_id is None:
                unassigned.append(
                    {
                        "annotation_set_id": annotation.annotation_set_id,
                        "reason": "review_artifact_missing",
                    }
                )
                continue
            reviewed_annotations.append(reviewed)
            source_asset_id = _annotation_source_asset(reviewed, source_by_id, lineage)
            source = source_by_id[source_asset_id]
            if source.retention_state != "active":
                excluded.append(
                    {
                        "annotation_set_id": reviewed.annotation_set_id,
                        "reason": f"source_retention_{source.retention_state}",
                    }
                )
                continue
            matching_uses = tuple(use for use in allowed if use in source.allowed_uses)
            if not matching_uses:
                excluded.append(
                    {
                        "annotation_set_id": reviewed.annotation_set_id,
                        "reason": "source_permission_does_not_allow_requested_use",
                    }
                )
                continue
            selected_use = intended_use or sorted(matching_uses)[0]
            if selected_use not in source.allowed_uses or selected_use not in allowed:
                excluded.append(
                    {
                        "annotation_set_id": reviewed.annotation_set_id,
                        "reason": "intended_use_not_allowed",
                    }
                )
                continue
            _assert_frame_lineage(reviewed, source_asset_id, lineage)
            eligibility = Eligibility(
                source_asset_id=source_asset_id,
                state="eligible",
                source_permission=source.source_permission,
                allowed_uses=source.allowed_uses,
                review_state="reviewed",
                annotation_set_id=reviewed.annotation_set_id,
                review_id=review_id,
                intended_use=selected_use,
            )
            annotation_entries = 0
            for card in reviewed.observed_cards:
                if card.visibility != "identifiable" or card.visual_card_identity is None:
                    continue
                for frame in card.frame_observations:
                    if not frame.usable_for_identity or frame.bbox is None:
                        continue
                    dataset_item_id = (
                        f"{reviewed.annotation_set_id}:{card.observed_card_id}:{frame.frame_id}"
                    )
                    entries.append(
                        DatasetEntry(
                            dataset_item_id=dataset_item_id,
                            source_asset_id=source_asset_id,
                            source_sha256=source.sha256,
                            annotation_set_id=reviewed.annotation_set_id,
                            review_id=review_id,
                            eligibility=eligibility,
                            target_schema=target_schema,
                            group_keys=_group_keys(source),
                            inclusion_reason=(
                                f"Reviewed {reviewed.event_review} table observation "
                                "with an identity-usable frame."
                            ),
                            transform_version=transform_version,
                            source_frame_id=frame.frame_id,
                            observed_card_id=card.observed_card_id,
                            bbox=(
                                frame.bbox.x_min,
                                frame.bbox.y_min,
                                frame.bbox.x_max,
                                frame.bbox.y_max,
                            ),
                            visual_card_identity=card.visual_card_identity,
                            quality_tags=frame.tags,
                        )
                    )
                    annotation_entries += 1
            if annotation_entries == 0:
                unassigned.append(
                    {
                        "annotation_set_id": reviewed.annotation_set_id,
                        "reason": "no_identity_usable_observed_card",
                    }
                )
        except (KeyError, ValueError) as exc:
            excluded.append(
                {
                    "annotation_set_id": annotation.annotation_set_id,
                    "reason": str(exc),
                }
            )
    if not entries:
        raise TableDatasetError(
            "No eligible identity samples were assembled; inspect the explicit "
            "unassigned/excluded output."
        )
    group_names = tuple(sorted({key for entry in entries for key, _ in entry.group_keys}))
    dataset_version = DatasetVersion(
        dataset_version_id=_id(dataset_version_id, "dataset_version_id"),
        task=task,
        target_schema=target_schema,
        entries=tuple(sorted(entries, key=lambda entry: entry.dataset_item_id)),
        allowed_use_filter=allowed,
        group_key_names=group_names,
        derived_artifact_transform_version=transform_version,
        creation_code_revision=creation_code_revision,
        dirty_state=dirty_state,
        deck_design_version=deck_design_version,
        card_set_version=card_set_version,
    )
    coverage = build_table_dataset_coverage(
        dataset_version,
        reviewed_annotations=tuple(reviewed_annotations),
        sources=tuple(source_by_id.values()),
        source_metadata=source_metadata,
        unassigned=tuple(unassigned),
        excluded=tuple(excluded),
    )
    return DatasetAssemblyResult(
        dataset_version=dataset_version,
        unassigned=tuple(unassigned),
        excluded=tuple(excluded),
        coverage=coverage,
    )


def save_dataset_version(
    dataset_version: DatasetVersion, path: str | Path, *, overwrite: bool = False
) -> Path:
    return _json_write(path, dataset_version.to_mapping(), overwrite=overwrite)


def load_dataset_version(path: str | Path) -> DatasetVersion:
    dataset_path = Path(path)
    try:
        return DatasetVersion.from_mapping(json.loads(dataset_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise TableDatasetError(f"Invalid dataset version {dataset_path}: {exc}") from exc


def save_assembly_result(
    result: DatasetAssemblyResult, path: str | Path, *, overwrite: bool = False
) -> Path:
    return _json_write(path, result.to_mapping(), overwrite=overwrite)


def _entry_groups(dataset: DatasetVersion) -> dict[str, set[str]]:
    token_to_index: dict[tuple[str, str], int] = {}
    parents = list(range(len(dataset.entries)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for index, entry in enumerate(dataset.entries):
        for token in entry.group_keys:
            previous = token_to_index.get(token)
            if previous is not None:
                union(previous, index)
            else:
                token_to_index[token] = index
    groups: dict[str, set[str]] = {}
    for index, entry in enumerate(dataset.entries):
        groups.setdefault(str(find(index)), set()).add(entry.dataset_item_id)
    return groups


def _split_counts(group_count: int) -> tuple[int, int, int]:
    train_count = max(1, round(group_count * 0.70)) if group_count else 0
    validation_count = max(1, round(group_count * 0.15)) if group_count >= 2 else 0
    test_count = group_count - train_count - validation_count
    while test_count < 1 and train_count > 1:
        train_count -= 1
        test_count = group_count - train_count - validation_count
    if test_count < 0:
        validation_count = max(0, validation_count + test_count)
        test_count = 0
    return train_count, validation_count, test_count


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    split_version_id: str
    dataset_version_id: str
    dataset_version_digest: str
    group_key_names: tuple[str, ...]
    seed: int
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    unassigned: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.split_version_id, "split_version_id")
        _id(self.dataset_version_id, "dataset_version_id")
        _sha(self.dataset_version_digest, "dataset_version_digest")
        if not self.group_key_names or len(set(self.group_key_names)) != len(self.group_key_names):
            raise TableDatasetError("A dataset split needs unique group key names.")
        all_ids = self.train + self.validation + self.test + self.unassigned
        if len(all_ids) != len(set(all_ids)):
            raise TableDatasetError("Dataset split item IDs must be unique across partitions.")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TableDatasetError("Dataset split seed must be an integer.")

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": TABLE_DATASET_SPLIT_SCHEMA_VERSION,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "group_key_names": sorted(self.group_key_names),
            "seed": self.seed,
            "train": sorted(self.train),
            "validation": sorted(self.validation),
            "test": sorted(self.test),
            "unassigned": sorted(self.unassigned),
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": TABLE_DATASET_SPLIT_SCHEMA_VERSION,
            "split_version_id": self.split_version_id,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "group_key_names": list(self.group_key_names),
            "seed": self.seed,
            "train": list(self.train),
            "validation": list(self.validation),
            "test": list(self.test),
            "unassigned": list(self.unassigned),
            "split_version_digest": self.digest,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DatasetSplit":
        fields = {
            "schema_version",
            "split_version_id",
            "dataset_version_id",
            "dataset_version_digest",
            "group_key_names",
            "seed",
            "train",
            "validation",
            "test",
            "unassigned",
            "split_version_digest",
        }
        if not isinstance(data, Mapping) or set(data) != fields:
            raise TableDatasetError("Dataset split has invalid fields.")
        if data["schema_version"] != TABLE_DATASET_SPLIT_SCHEMA_VERSION:
            raise TableDatasetError("Unsupported dataset split schema.")
        partitions: dict[str, tuple[str, ...]] = {}
        for name in ("train", "validation", "test", "unassigned"):
            values = data[name]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise TableDatasetError(f"Dataset split {name} must be a list of IDs.")
            partitions[name] = tuple(values)
        group_names = data["group_key_names"]
        if not isinstance(group_names, list) or any(
            not isinstance(value, str) or not value for value in group_names
        ):
            raise TableDatasetError("Dataset split group_key_names must be a list of strings.")
        split = cls(
            split_version_id=_id(data["split_version_id"], "split_version_id"),
            dataset_version_id=_id(data["dataset_version_id"], "dataset_version_id"),
            dataset_version_digest=_sha(data["dataset_version_digest"], "dataset_version_digest"),
            group_key_names=tuple(group_names),
            seed=data["seed"],
            **partitions,
        )
        if split.digest != _sha(data["split_version_digest"], "split_version_digest"):
            raise TableDatasetError("split_version_digest does not match the split contents.")
        return split

    def validate_against(self, dataset: DatasetVersion) -> None:
        if self.dataset_version_id != dataset.dataset_version_id:
            raise TableDatasetError("Dataset split references a different dataset version ID.")
        if self.dataset_version_digest != dataset.digest:
            raise TableDatasetError("Dataset split references a different dataset digest.")
        if set(self.group_key_names) != set(dataset.group_key_names):
            raise TableDatasetError("Dataset split group keys do not match the dataset version.")
        expected = {entry.dataset_item_id for entry in dataset.entries}
        actual = set(self.train + self.validation + self.test + self.unassigned)
        if expected != actual:
            missing = ", ".join(sorted(expected - actual))
            extra = ", ".join(sorted(actual - expected))
            raise TableDatasetError(
                f"Dataset split item mismatch (missing: {missing}; extra: {extra})."
            )
        groups = _entry_groups(dataset)
        partition_by_item = {
            item_id: partition
            for partition in ("train", "validation", "test", "unassigned")
            for item_id in getattr(self, partition)
        }
        for items in groups.values():
            partitions = {partition_by_item[item] for item in items}
            if len(partitions) > 1:
                raise TableDatasetError(
                    "A session, game, table setup, or source lineage group crosses "
                    "dataset partitions."
                )


def make_dataset_split(
    dataset: DatasetVersion,
    *,
    split_version_id: str = "table-evidence-split-v1",
    seed: int = 42,
    assignments: Mapping[str, str] | None = None,
) -> DatasetSplit:
    """Create a deterministic split over connected leakage groups.

    ``assignments`` is an optional reviewed item-to-partition mapping. Omitted items are explicit
    ``unassigned`` records; a group cannot be partly assigned.
    """

    groups = _entry_groups(dataset)
    group_values = sorted(groups.values(), key=lambda values: tuple(sorted(values)))
    group_partitions: dict[int, str] = {}
    if assignments is None:
        shuffled = list(range(len(group_values)))
        random.Random(seed).shuffle(shuffled)
        train_count, validation_count, _ = _split_counts(len(shuffled))
        for position, group_index in enumerate(shuffled):
            group_partitions[group_index] = (
                "train"
                if position < train_count
                else "validation"
                if position < train_count + validation_count
                else "test"
            )
    else:
        valid_partitions = {"train", "validation", "test", "unassigned"}
        item_to_group = {
            item_id: index for index, group in enumerate(group_values) for item_id in group
        }
        unknown = set(assignments) - set(item_to_group)
        if unknown:
            raise TableDatasetError(
                f"Split assignments name unknown items: {', '.join(sorted(unknown))}."
            )
        for item_id, partition in assignments.items():
            if partition not in valid_partitions:
                raise TableDatasetError(f"Unknown dataset split partition: {partition}.")
            group_index = item_to_group[item_id]
            previous = group_partitions.get(group_index)
            if previous is not None and previous != partition:
                raise TableDatasetError("A leakage group has conflicting split assignments.")
            group_partitions[group_index] = partition
        for group_index in range(len(group_values)):
            group_partitions.setdefault(group_index, "unassigned")
    partitions: dict[str, list[str]] = {
        name: [] for name in ("train", "validation", "test", "unassigned")
    }
    for group_index, group in enumerate(group_values):
        partitions[group_partitions[group_index]].extend(sorted(group))
    split = DatasetSplit(
        split_version_id=split_version_id,
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        group_key_names=dataset.group_key_names,
        seed=seed,
        train=tuple(sorted(partitions["train"])),
        validation=tuple(sorted(partitions["validation"])),
        test=tuple(sorted(partitions["test"])),
        unassigned=tuple(sorted(partitions["unassigned"])),
    )
    split.validate_against(dataset)
    return split


def save_dataset_split(split: DatasetSplit, path: str | Path, *, overwrite: bool = False) -> Path:
    return _json_write(path, split.to_mapping(), overwrite=overwrite)


def load_dataset_split(path: str | Path) -> DatasetSplit:
    split_path = Path(path)
    try:
        return DatasetSplit.from_mapping(json.loads(split_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise TableDatasetError(f"Invalid dataset split {split_path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    dataset_version_id: str
    dataset_version_digest: str
    checked_entry_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "table-dataset-validation/v1",
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "checked_entry_count": self.checked_entry_count,
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def validate_dataset_version(
    dataset: DatasetVersion,
    *,
    sources: Sequence[SourceRecord] = (),
    annotations: Sequence[TableObservationAnnotation] = (),
    reviews: Any = None,
    lineage: LineageGraph | None = None,
    split: DatasetSplit | None = None,
) -> DatasetValidationReport:
    """Validate a frozen dataset and all supplied source, label, and split evidence."""

    errors: list[str] = []
    warnings: list[str] = []
    source_by_id: dict[str, SourceRecord] = {}
    try:
        source_by_id = _source_mapping(sources) if sources else {}
    except TableDatasetError as exc:
        errors.append(str(exc))
    try:
        annotation_values = _as_annotations(annotations)
    except TableDatasetError as exc:
        return DatasetValidationReport(
            dataset_version_id=dataset.dataset_version_id,
            dataset_version_digest=dataset.digest,
            checked_entry_count=len(dataset.entries),
            errors=(str(exc),),
        )
    annotation_by_id = {
        annotation.annotation_set_id: annotation for annotation in annotation_values
    }
    try:
        review_by_id = _review_mapping(reviews)
    except TableDatasetError as exc:
        errors.append(str(exc))
        review_by_id = {}
    if lineage is not None:
        try:
            lineage.validate()
        except ValueError as exc:
            errors.append(str(exc))
    seen_sample_keys: dict[tuple[str, str | None, str | None], str] = {}
    source_digests: dict[str, str] = {}
    for entry in dataset.entries:
        source = source_by_id.get(entry.source_asset_id)
        if source is None and sources:
            errors.append(f"Entry {entry.dataset_item_id} references an unknown source asset.")
        if source is not None:
            if source.sha256 != entry.source_sha256:
                errors.append(f"Entry {entry.dataset_item_id} has a changed source SHA-256.")
            if source.retention_state != "active":
                errors.append(f"Entry {entry.dataset_item_id} uses a non-active source asset.")
            if not set(source.allowed_uses).intersection(dataset.allowed_use_filter):
                errors.append(
                    f"Entry {entry.dataset_item_id} does not pass the allowed-use filter."
                )
            other = source_digests.get(source.sha256)
            if other is not None and other != source.source_asset_id:
                errors.append(
                    f"Duplicate source bytes occur in entries {other} and {source.source_asset_id}."
                )
            source_digests[source.sha256] = source.source_asset_id
        if entry.source_frame_id is None:
            errors.append(f"Entry {entry.dataset_item_id} has no source frame reference.")
        else:
            key = (
                entry.source_asset_id,
                entry.source_frame_id,
                entry.observed_card_id,
            )
            previous = seen_sample_keys.get(key)
            if previous is not None and previous != entry.dataset_item_id:
                errors.append(
                    f"Duplicate dataset sample references {previous} and {entry.dataset_item_id}."
                )
            seen_sample_keys[key] = entry.dataset_item_id
        annotation = annotation_by_id.get(entry.annotation_set_id)
        if annotations and annotation is None:
            errors.append(f"Entry {entry.dataset_item_id} references an unknown annotation set.")
        if annotation is not None:
            try:
                if annotation.review_state != "reviewed":
                    errors.append(f"Entry {entry.dataset_item_id} uses an unreviewed annotation.")
                if lineage is not None and source is not None:
                    resolved_annotation_source = _annotation_source_asset(
                        annotation, source_by_id, lineage
                    )
                    if resolved_annotation_source != source.source_asset_id:
                        errors.append(
                            f"Entry {entry.dataset_item_id} has invalid annotation lineage."
                        )
                card = next(
                    card
                    for card in annotation.observed_cards
                    if card.observed_card_id == entry.observed_card_id
                )
                frame = next(
                    frame
                    for frame in card.frame_observations
                    if frame.frame_id == entry.source_frame_id
                )
                expected_bbox = (
                    (
                        frame.bbox.x_min,
                        frame.bbox.y_min,
                        frame.bbox.x_max,
                        frame.bbox.y_max,
                    )
                    if frame.bbox is not None
                    else None
                )
                if (
                    card.visual_card_identity != entry.visual_card_identity
                    or expected_bbox != entry.bbox
                ):
                    errors.append(
                        f"Entry {entry.dataset_item_id} target does not match its annotation."
                    )
            except (KeyError, StopIteration, ValueError) as exc:
                errors.append(
                    f"Entry {entry.dataset_item_id} target or annotation lineage is invalid: {exc}"
                )
            review = review_by_id.get(entry.annotation_set_id)
            if reviews is not None and (
                review is None or getattr(review, "review_id", None) != entry.review_id
            ):
                errors.append(
                    f"Entry {entry.dataset_item_id} review version is missing or changed."
                )
        if lineage is not None and entry.source_frame_id is not None and source is not None:
            try:
                resolved = lineage.single_source_asset_for(
                    EntityRef("frame", entry.source_frame_id)
                ).id
                if resolved != source.source_asset_id:
                    errors.append(f"Entry {entry.dataset_item_id} has invalid frame lineage.")
            except (KeyError, ValueError) as exc:
                errors.append(f"Entry {entry.dataset_item_id} has invalid frame lineage: {exc}")
    if split is not None:
        try:
            split.validate_against(dataset)
        except TableDatasetError as exc:
            errors.append(str(exc))
    if not sources:
        warnings.append(
            "Source records were not supplied; source bytes and permission were not rechecked."
        )
    if not annotation_values:
        warnings.append(
            "Annotations were not supplied; target and review snapshots were not rechecked."
        )
    return DatasetValidationReport(
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        checked_entry_count=len(dataset.entries),
        errors=tuple(sorted(set(errors))),
        warnings=tuple(sorted(set(warnings))),
    )


def assert_valid_dataset_version(*args: Any, **kwargs: Any) -> DatasetValidationReport:
    report = validate_dataset_version(*args, **kwargs)
    if not report.valid:
        raise TableDatasetError("Dataset validation failed: " + "; ".join(report.errors))
    return report


def _counter(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _metadata_value(source: SourceRecord, metadata: Mapping[str, Any] | Any, name: str) -> Any:
    value = metadata.get(name) if isinstance(metadata, Mapping) else getattr(metadata, name, None)
    return getattr(source, name, None) if value is None else value


def build_table_dataset_coverage(
    dataset: DatasetVersion,
    *,
    reviewed_annotations: Sequence[TableObservationAnnotation],
    sources: Sequence[SourceRecord] = (),
    source_metadata: Mapping[str, Mapping[str, Any] | Any] | None = None,
    unassigned: Sequence[Mapping[str, Any]] = (),
    excluded: Sequence[Mapping[str, Any]] = (),
    evidence_completeness: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Build the machine-readable coverage report for one dataset version."""

    event_reviews: list[str] = []
    visibilities: list[str] = []
    identities: list[str] = []
    active_areas: list[str] = []
    movements: list[str] = []
    occlusions: list[str] = []
    newly_visible: list[str] = []
    quality_tags: list[str] = []
    crop_sizes: list[str] = []
    visible_card_counts: list[str] = []
    source_values: dict[str, list[str]] = {
        "session_id": [],
        "game_id": [],
        "round_id": [],
        "table_setup": [],
        "content_type": [],
        "device_class": [],
        "deck_design": [],
        "physical_card_id": [],
    }
    selected_frame_count = 0
    snippet_count = 0
    tracklet_ids: set[str] = set()
    for annotation in reviewed_annotations:
        event_reviews.append(annotation.event_review)
        selected_frame_count += len(
            {
                frame.frame_id
                for card in annotation.observed_cards
                for frame in card.frame_observations
            }
        )
        snippet_count += annotation.video_snippet is not None
        visible_card_counts.append(str(len(annotation.observed_cards)))
        for card in annotation.observed_cards:
            visibilities.append(card.visibility)
            if card.visual_card_identity is not None:
                identities.append(card.visual_card_identity)
            if card.active_area_class is not None:
                active_areas.append(card.active_area_class)
            if card.movement is not None:
                movements.append(card.movement)
            if card.occlusion is not None:
                occlusions.append(card.occlusion)
            newly_visible.append(str(card.became_newly_visible).lower())
            if card.card_tracklet_id is not None:
                tracklet_ids.add(card.card_tracklet_id)
            for frame in card.frame_observations:
                quality_tags.extend(frame.tags)
                if frame.bbox is not None:
                    crop_sizes.append(
                        f"{frame.bbox.x_max - frame.bbox.x_min}x"
                        f"{frame.bbox.y_max - frame.bbox.y_min}"
                    )
    source_by_id = {source.source_asset_id: source for source in sources}
    source_metadata = source_metadata or {}
    for source in sources:
        metadata = source_metadata.get(source.source_asset_id, source)
        for name in source_values:
            value = _metadata_value(source, metadata, name)
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                source_values[name].extend(str(item) for item in value)
            else:
                source_values[name].append(str(value))
    complete = {
        "complete": 0,
        "incomplete": 0,
        "unknown": 0,
    }
    if evidence_completeness is not None:
        for complete_value in evidence_completeness.values():
            complete["complete" if complete_value else "incomplete"] += 1
    else:
        complete["unknown"] = len(
            {annotation.source.source_id for annotation in reviewed_annotations}
        )
    return {
        "schema_version": TABLE_DATASET_COVERAGE_SCHEMA_VERSION,
        "dataset_version_id": dataset.dataset_version_id,
        "dataset_version_digest": dataset.digest,
        "counts": {
            "dataset_entries": len(dataset.entries),
            "annotation_sets": len(reviewed_annotations),
            "source_assets": len(source_by_id),
            "selected_frames": selected_frame_count,
            "video_snippets": snippet_count,
            "reviewed_card_tracklets": len(tracklet_ids),
            "unassigned": len(unassigned),
            "excluded": len(excluded),
        },
        "event_review": _counter(event_reviews),
        "visual_card_identity": _counter(identities),
        "visibility": _counter(visibilities),
        "quality": {
            "tags": _counter(quality_tags),
            "crop_sizes": _counter(crop_sizes),
            "newly_visible": _counter(newly_visible),
            "active_area": _counter(active_areas),
            "movement": _counter(movements),
            "occlusion": _counter(occlusions),
        },
        "visible_card_count": _counter(visible_card_counts),
        "evidence_completeness": complete,
        "source_coverage": {name: _counter(values) for name, values in source_values.items()},
        "unassigned": [dict(item) for item in unassigned],
        "excluded": [dict(item) for item in excluded],
    }


def coverage_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a deterministic human-readable coverage report."""

    lines = [
        "# TableEvidenceAnalyzer dataset coverage",
        "",
        f"- Dataset version: `{report['dataset_version_id']}`",
        f"- Dataset digest: `{report['dataset_version_digest']}`",
        "",
        "## Counts",
        "",
    ]
    for name, value in sorted(report["counts"].items()):
        lines.append(f"- {name}: {value}")
    for section in (
        "event_review",
        "visual_card_identity",
        "visibility",
        "visible_card_count",
        "evidence_completeness",
    ):
        lines.extend(["", f"## {section.replace('_', ' ').title()}", ""])
        for name, value in sorted(report[section].items()):
            lines.append(f"- {name}: {value}")
    for section, values in (
        ("quality", report["quality"]),
        ("source_coverage", report["source_coverage"]),
    ):
        lines.extend(["", f"## {section.replace('_', ' ').title()}", ""])
        for name, counts in sorted(values.items()):
            lines.append(f"- {name}: {counts}")
    for section in ("unassigned", "excluded"):
        lines.extend(["", f"## {section.title()}", ""])
        items = report[section]
        if not items:
            lines.append("- None")
        else:
            lines.extend(f"- {item}" for item in items)
    return "\n".join(lines) + "\n"


def save_coverage_reports(
    report: Mapping[str, Any], output_dir: str | Path, *, overwrite: bool = False
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    machine = _json_write(output_path / "coverage.json", report, overwrite=overwrite)
    human = output_path / "coverage.md"
    if human.exists() and not overwrite:
        raise TableDatasetError(f"Refusing to overwrite file: {human}")
    human.parent.mkdir(parents=True, exist_ok=True)
    human.write_text(coverage_report_markdown(report), encoding="utf-8")
    return machine, human


def save_validation_report(
    report: DatasetValidationReport, path: str | Path, *, overwrite: bool = False
) -> Path:
    return _json_write(path, report.to_mapping(), overwrite=overwrite)


__all__ = [
    "DEFAULT_ALLOWED_USES",
    "DEFAULT_TABLE_DATASET_GROUP_KEYS",
    "DEFAULT_TABLE_DATASET_TRANSFORM_VERSION",
    "DatasetAssemblyResult",
    "DatasetSplit",
    "DatasetValidationReport",
    "TABLE_DATASET_COVERAGE_SCHEMA_VERSION",
    "TABLE_DATASET_SPLIT_SCHEMA_VERSION",
    "TABLE_EVIDENCE_DATASET_TASK",
    "TableDatasetError",
    "assemble_table_evidence_dataset",
    "assert_valid_dataset_version",
    "build_table_dataset_coverage",
    "coverage_report_markdown",
    "load_dataset_split",
    "load_dataset_version",
    "load_lineage_graph",
    "load_source_records",
    "load_source_metadata",
    "load_table_observation_annotations",
    "load_table_observation_reviews",
    "make_dataset_split",
    "save_assembly_result",
    "save_coverage_reports",
    "save_dataset_split",
    "save_dataset_version",
    "save_validation_report",
    "validate_dataset_version",
]
