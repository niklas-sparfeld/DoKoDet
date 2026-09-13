"""Load and verify a materialized frozen CardEventNet run view."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MATERIALIZATION_SCHEMA_VERSION = "cardeventnet-materialization/v1"


class RunViewError(ValueError):
    """The materialized CardEventNet run view is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class MaterializedRunView:
    """Paths and immutable lineage loaded from one materialization manifest."""

    root: Path
    manifest: Mapping[str, Any]

    @property
    def split_path(self) -> Path:
        return self.root / "split.yaml"

    @property
    def videos_dir(self) -> Path:
        return self.root / "videos"

    @property
    def annotations_dir(self) -> Path:
        return self.root / "annotations"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def dataset(self) -> Mapping[str, str]:
        return self._artifact("dataset")

    @property
    def split(self) -> Mapping[str, str]:
        return self._artifact("split")

    @property
    def manifest_digest(self) -> str:
        return str(self.manifest["manifest_digest"])

    def video_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                path
                for path in self.videos_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".mov", ".m4v", ".mp4"}
            )
        )

    def data_identity(self, *, preprocessing: str) -> dict[str, Any]:
        """Return the lineage that a train or evaluation run must retain."""
        inputs = self.manifest.get("inputs", [])
        if not isinstance(inputs, list):
            raise RunViewError("materialization inputs are invalid")
        source_inputs = [
            dict(item)
            for item in inputs
            if isinstance(item, Mapping) and item.get("kind") == "source_video"
        ]
        event_references = [
            dict(item)
            for item in inputs
            if isinstance(item, Mapping)
            and item.get("kind") in {"event_reference_manifest", "event_reference_content"}
        ]
        return {
            "dataset": dict(self.dataset),
            "split": dict(self.split),
            "materializer": {
                "schema_version": self.manifest["schema_version"],
                "version": self.manifest["materializer_version"],
                "manifest_digest": self.manifest_digest,
            },
            "source_inputs": source_inputs,
            "event_references": event_references,
            "preprocessing": preprocessing,
        }

    def _artifact(self, key: str) -> Mapping[str, str]:
        value = self.manifest.get(key)
        if not isinstance(value, Mapping):
            raise RunViewError(f"materialization {key} identity is invalid")
        return value


def load_materialized_run_view(path: str | Path) -> MaterializedRunView:
    """Read the manifest and verify every generated file before a command uses the view."""

    root = Path(path).expanduser().resolve()
    manifest_path = root / "materialization.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunViewError(
            f"could not read materialization manifest {manifest_path}: {error}"
        ) from error
    if not isinstance(manifest, Mapping):
        raise RunViewError("materialization manifest must be an object")
    if manifest.get("schema_version") != MATERIALIZATION_SCHEMA_VERSION:
        raise RunViewError("materialization manifest has an unsupported schema")
    manifest_digest = manifest.get("manifest_digest")
    if (
        not isinstance(manifest_digest, str)
        or _mapping_digest(_without_digest(manifest)) != manifest_digest
    ):
        raise RunViewError("materialization manifest digest is invalid")
    for key in ("dataset", "split", "inputs", "generated_files"):
        if key not in manifest:
            raise RunViewError(f"materialization manifest is missing {key}")
    generated_files = manifest["generated_files"]
    if not isinstance(generated_files, list):
        raise RunViewError("materialization generated_files must be a list")
    for item in generated_files:
        if not isinstance(item, Mapping):
            raise RunViewError("materialization generated file is not an object")
        relative_path = item.get("path")
        if not isinstance(relative_path, str):
            raise RunViewError("materialization generated file path is invalid")
        generated_path = _safe_child(root, relative_path)
        if not generated_path.is_file():
            raise RunViewError(f"materialized file is missing: {relative_path}")
        expected_digest = item.get("sha256")
        if not isinstance(expected_digest, str) or _sha256_file(generated_path) != expected_digest:
            raise RunViewError(f"materialized file digest is invalid: {relative_path}")
    for relative_path in ("split.yaml",):
        if not _safe_child(root, relative_path).is_file():
            raise RunViewError(f"materialized run view is missing {relative_path}")
    for directory_name in ("videos", "annotations", "cache"):
        if not (root / directory_name).is_dir():
            raise RunViewError(f"materialized run view is missing {directory_name}/")
    if not any(path.is_file() for path in (root / "videos").iterdir()):
        raise RunViewError("materialized run view contains no videos")
    return MaterializedRunView(root=root, manifest=manifest)


def _without_digest(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "manifest_digest"}


def _safe_child(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
        raise RunViewError(f"materialized path is unsafe: {relative_path}")
    candidate = root / Path(*path.parts)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise RunViewError(f"materialized path escapes view: {relative_path}") from error
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RunViewError(f"could not hash materialized file {path}: {error}") from error
    return digest.hexdigest()


def _mapping_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["MaterializedRunView", "RunViewError", "load_materialized_run_view"]
