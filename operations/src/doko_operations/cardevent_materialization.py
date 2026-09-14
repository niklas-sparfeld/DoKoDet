"""Materialize a frozen CardEventNet dataset into a disposable trainer view."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .cardevent_dataset import (
    CardEventNetDatasetFreezeError,
    _read_object,
    _validate_dataset,
)

CARD_EVENTNET_MATERIALIZATION_SCHEMA_VERSION = "cardeventnet-materialization/v1"
CARD_EVENTNET_MATERIALIZER_VERSION = "cardeventnet-materializer/v1"
CARD_EVENTNET_INTERVAL_POLICY = "stable-end-anchor-v1"
_DIGEST_LENGTH = 64


class CardEventNetMaterializationError(ValueError):
    """The frozen CardEventNet dataset cannot be materialized."""


@dataclass(frozen=True, slots=True)
class CardEventNetMaterializationResult:
    """The published disposable run view and its immutable input identity."""

    view_root: Path
    dataset_version_id: str
    dataset_version_digest: str
    split_version_id: str
    split_version_digest: str
    manifest_digest: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "view_root": str(self.view_root),
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "split_version_id": self.split_version_id,
            "split_version_digest": self.split_version_digest,
            "manifest_digest": self.manifest_digest,
        }


def materialize_cardeventnet_dataset(
    dataset_path: str | Path,
    *,
    repository_root: str | Path,
    output_root: str | Path | None = None,
) -> CardEventNetMaterializationResult:
    """Build one deterministic, disposable CardEventNet run view.

    Source videos stay in canonical intake. The view links to those immutable bytes and creates
    only derived annotations, a split, and a manifest under ``.runtime/cardevent``.
    """

    repository = Path(repository_root).expanduser().resolve()
    dataset_directory = _dataset_directory(dataset_path, repository)
    dataset = _required_object(dataset_directory / "dataset.json", "dataset")
    split = _required_object(dataset_directory / "split.json", "split")
    coverage = _required_object(dataset_directory / "coverage.json", "coverage")
    receipt = _required_object(dataset_directory / "receipt.json", "receipt")
    try:
        _validate_dataset(dataset, split, coverage, receipt, repository)
    except (CardEventNetDatasetFreezeError, ValueError) as error:
        raise CardEventNetMaterializationError(f"frozen dataset is invalid: {error}") from error

    dataset_id = _identifier(dataset.get("dataset_version_id"), "dataset_version_id")
    dataset_digest = _digest(dataset.get("dataset_version_digest"), "dataset_version_digest")
    split_id = _identifier(split.get("split_version_id"), "split_version_id")
    split_digest = _digest(split.get("split_version_digest"), "split_version_digest")
    destination = _output_directory(
        repository,
        output_root,
        dataset_id,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    staging_parent = Path(
        tempfile.mkdtemp(prefix=".cardevent-materialization-", dir=destination.parent)
    )
    staging = staging_parent / destination.name
    try:
        videos_dir = staging / "videos"
        annotations_dir = staging / "annotations"
        cache_dir = staging / "cache"
        videos_dir.mkdir(parents=True)
        annotations_dir.mkdir()
        cache_dir.mkdir()

        entries = dataset.get("entries")
        if not isinstance(entries, list):  # guarded by the frozen dataset validator
            raise CardEventNetMaterializationError("frozen dataset entries are not a list")
        generated_files: list[dict[str, Any]] = []
        inputs: list[dict[str, Any]] = []
        split_values: dict[str, list[str]] = {"train": [], "val": [], "test": []}
        for entry in sorted(entries, key=lambda item: str(item.get("recording_id", ""))):
            if not isinstance(entry, Mapping):
                raise CardEventNetMaterializationError("frozen dataset entry is not an object")
            recording_id = _identifier(entry.get("recording_id"), "recording_id")
            partition = entry.get("partition")
            if partition not in {"train", "validation", "test"}:
                raise CardEventNetMaterializationError(
                    f"dataset entry {recording_id} has an invalid partition"
                )
            source_path = _relative_path(entry.get("source_path"), "source_path")
            source = (repository / source_path).resolve()
            source_digest = _digest(entry.get("source_sha256"), f"{recording_id}.source_sha256")
            if not source.is_file():
                raise CardEventNetMaterializationError(f"source is missing for {recording_id}")
            if _sha256_file(source) != source_digest:
                raise CardEventNetMaterializationError(f"source digest differs for {recording_id}")
            source_suffix = Path(source_path).suffix.lower()
            if not source_suffix:
                raise CardEventNetMaterializationError(
                    f"source path has no video extension for {recording_id}"
                )
            video_name = f"{recording_id}{source_suffix}"
            video_destination = videos_dir / video_name
            _link_source(source, video_destination)
            generated_files.append(
                {
                    "kind": "source_link",
                    "path": f"videos/{video_name}",
                    "recording_id": recording_id,
                    "canonical_path": source_path,
                    "sha256": _sha256_file(video_destination),
                }
            )
            inputs.append(
                {
                    "kind": "source_video",
                    "recording_id": recording_id,
                    "path": source_path,
                    "sha256": source_digest,
                    "byte_length": source.stat().st_size,
                }
            )

            manifest_path = _relative_path(
                entry.get("event_revision_manifest_path"),
                f"{recording_id}.event_revision_manifest_path",
            )
            content_path = _relative_path(
                entry.get("event_revision_content_path"),
                f"{recording_id}.event_revision_content_path",
            )
            manifest_file = (repository / manifest_path).resolve()
            content_file = (repository / content_path).resolve()
            manifest_digest = _digest(
                entry.get("event_revision_manifest_sha256"),
                f"{recording_id}.event_revision_manifest_sha256",
            )
            content_digest = _digest(
                entry.get("event_revision_content_sha256"),
                f"{recording_id}.event_revision_content_sha256",
            )
            if _sha256_file(manifest_file) != manifest_digest:
                raise CardEventNetMaterializationError(
                    f"event reference manifest digest differs for {recording_id}"
                )
            if _sha256_file(content_file) != content_digest:
                raise CardEventNetMaterializationError(
                    f"event reference content digest differs for {recording_id}"
                )
            events = _load_events(content_file, recording_id)
            expected_event_count = entry.get("event_count")
            if expected_event_count != len(events):
                raise CardEventNetMaterializationError(
                    f"event count differs for {recording_id}: "
                    f"dataset says {expected_event_count}, content has {len(events)}"
                )
            inputs.extend(
                (
                    {
                        "kind": "event_reference_manifest",
                        "recording_id": recording_id,
                        "path": manifest_path,
                        "sha256": manifest_digest,
                    },
                    {
                        "kind": "event_reference_content",
                        "recording_id": recording_id,
                        "path": content_path,
                        "sha256": content_digest,
                    },
                )
            )
            annotation_name = f"{recording_id}.json"
            annotation_destination = annotations_dir / annotation_name
            annotation_payload = {
                "schema_version": "cardevent-annotation/v2",
                "video": video_name,
                "events": [_annotation_event(start_us, end_us) for start_us, end_us in events],
            }
            annotation_bytes = _json_bytes(annotation_payload)
            annotation_destination.write_bytes(annotation_bytes)
            generated_files.append(
                {
                    "kind": "event_annotation",
                    "path": f"annotations/{annotation_name}",
                    "recording_id": recording_id,
                    "source_path": content_path,
                    "source_sha256": content_digest,
                    "sha256": _sha256_file(annotation_destination),
                }
            )
            split_key = "val" if partition == "validation" else partition
            split_values[split_key].append(recording_id)

        split_payload = {
            "train": sorted(split_values["train"]),
            "val": sorted(split_values["val"]),
            "test": sorted(split_values["test"]),
        }
        split_file = staging / "split.yaml"
        split_file.write_text(_yaml_text(split_payload), encoding="utf-8")
        generated_files.append(
            {
                "kind": "trainer_split",
                "path": "split.yaml",
                "sha256": _sha256_file(split_file),
            }
        )
        generated_files.sort(key=lambda item: str(item["path"]))
        inputs.sort(
            key=lambda item: (
                str(item["kind"]),
                str(item["recording_id"]),
                str(item["path"]),
            )
        )
        manifest_core: dict[str, Any] = {
            "schema_version": CARD_EVENTNET_MATERIALIZATION_SCHEMA_VERSION,
            "materializer_version": CARD_EVENTNET_MATERIALIZER_VERSION,
            "dataset": {"id": dataset_id, "digest": dataset_digest},
            "split": {"id": split_id, "digest": split_digest},
            "event_target_policy": {
                "version": CARD_EVENTNET_INTERVAL_POLICY,
                "anchor": "end_us",
                "interval_interior": "exclude_from_negative_evidence",
            },
            "inputs": inputs,
            "generated_files": generated_files,
        }
        manifest = {
            **manifest_core,
            "manifest_digest": _mapping_digest(manifest_core),
        }
        manifest_file = staging / "materialization.json"
        manifest_file.write_bytes(_json_bytes(manifest))
        existing_cache = destination / "cache"
        if existing_cache.is_dir() and not existing_cache.is_symlink():
            shutil.rmtree(staging / "cache")
            os.replace(existing_cache, staging / "cache")
        if destination.exists() or destination.is_symlink():
            _remove_destination(destination)
        os.replace(staging, destination)
        return CardEventNetMaterializationResult(
            view_root=destination,
            dataset_version_id=dataset_id,
            dataset_version_digest=dataset_digest,
            split_version_id=split_id,
            split_version_digest=split_digest,
            manifest_digest=str(manifest["manifest_digest"]),
        )
    except CardEventNetMaterializationError:
        raise
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise CardEventNetMaterializationError(f"could not materialize dataset: {error}") from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _dataset_directory(dataset_path: str | Path, repository: Path) -> Path:
    candidate = Path(dataset_path).expanduser()
    resolved = (repository / candidate if not candidate.is_absolute() else candidate).resolve()
    if resolved.is_file() and resolved.name == "dataset.json":
        return resolved.parent
    if resolved.is_dir():
        return resolved
    raise CardEventNetMaterializationError(f"dataset directory does not exist: {resolved}")


def _output_directory(repository: Path, output_root: str | Path | None, dataset_id: str) -> Path:
    if output_root is None:
        return repository / ".runtime" / "cardevent" / "datasets" / dataset_id
    candidate = Path(output_root).expanduser()
    return (repository / candidate if not candidate.is_absolute() else candidate).resolve()


def _required_object(path: Path, name: str) -> dict[str, Any]:
    value = _read_object(path)
    if value is None:
        raise CardEventNetMaterializationError(f"{name} artifact is missing or invalid: {path}")
    return value


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CardEventNetMaterializationError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise CardEventNetMaterializationError(f"{field} must be a safe relative path")
    return path.as_posix()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise CardEventNetMaterializationError(f"{field} must be an identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _DIGEST_LENGTH:
        raise CardEventNetMaterializationError(f"{field} must be a SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise CardEventNetMaterializationError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _load_events(path: Path, recording_id: str) -> list[tuple[int, int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetMaterializationError(
            f"could not read event reference content for {recording_id}: {error}"
        ) from error
    raw_events = payload.get("events") if isinstance(payload, Mapping) else None
    if not isinstance(raw_events, list):
        raise CardEventNetMaterializationError(
            f"event reference content for {recording_id} has no events list"
        )
    result: list[tuple[int, int]] = []
    for index, raw_event in enumerate(raw_events):
        if (
            not isinstance(raw_event, Mapping)
            or raw_event.get("event_type") != "card_state_changed"
        ):
            raise CardEventNetMaterializationError(
                f"event reference {recording_id}[{index}] is not card_state_changed"
            )
        start_us = raw_event.get("start_us")
        end_us = raw_event.get("end_us")
        if (
            isinstance(start_us, bool)
            or not isinstance(start_us, int)
            or start_us < 0
            or isinstance(end_us, bool)
            or not isinstance(end_us, int)
            or end_us < start_us
        ):
            raise CardEventNetMaterializationError(
                f"event reference {recording_id}[{index}] has invalid interval"
            )
        result.append((start_us, end_us))
    end_times = [end_us for _, end_us in result]
    if (
        result != sorted(result)
        or len(result) != len({start_us for start_us, _ in result})
        or end_times != sorted(end_times)
        or len(end_times) != len(set(end_times))
    ):
        raise CardEventNetMaterializationError(
            f"event reference {recording_id} is not strictly ordered"
        )
    return result


def _annotation_event(start_us: int, end_us: int) -> dict[str, Any]:
    event: dict[str, Any] = {
        "time_s": end_us / 1_000_000,
        "type": "card_state_changed",
    }
    if start_us != end_us:
        event.update(
            {
                "start_s": start_us / 1_000_000,
                "end_s": end_us / 1_000_000,
            }
        )
    return event


def _link_source(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, destination)


def _remove_destination(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CardEventNetMaterializationError(f"could not hash file {path}: {error}") from error
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _yaml_text(value: Mapping[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(dict(value), sort_keys=False)
    except ModuleNotFoundError as error:
        raise CardEventNetMaterializationError(
            "PyYAML is not available; run `uv sync` to install operations dependencies"
        ) from error


def _mapping_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CARD_EVENTNET_MATERIALIZATION_SCHEMA_VERSION",
    "CARD_EVENTNET_MATERIALIZER_VERSION",
    "CARD_EVENTNET_INTERVAL_POLICY",
    "CardEventNetMaterializationError",
    "CardEventNetMaterializationResult",
    "materialize_cardeventnet_dataset",
]
