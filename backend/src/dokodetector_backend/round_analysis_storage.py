"""Atomic runtime storage for round-analysis input and result artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredRoundAnalysisArtifact:
    """Digest and relative path for one published analysis artifact."""

    relative_path: str
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StoredRoundAnalysisArtifacts:
    """The two artifacts published for one analysis."""

    analysis_id: UUID
    input: StoredRoundAnalysisArtifact
    result: StoredRoundAnalysisArtifact


@dataclass(frozen=True, slots=True)
class StoredCounterfactualArtifacts:
    """The three immutable artifacts published for one counterfactual."""

    source_analysis_id: UUID
    counterfactual_id: UUID
    request: StoredRoundAnalysisArtifact
    input: StoredRoundAnalysisArtifact
    result: StoredRoundAnalysisArtifact


@dataclass(frozen=True, slots=True)
class StoredCounterfactualContents:
    """Verified counterfactual bytes and their recorded artifact identities."""

    artifacts: StoredCounterfactualArtifacts
    request_bytes: bytes
    input_bytes: bytes
    result_bytes: bytes


COUNTERFACTUAL_MANIFEST_SCHEMA_VERSION = "round-analysis-counterfactual-artifacts/v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RoundAnalysisArtifactStorage:
    """Publish immutable analysis artifacts below a disposable runtime root."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.root = self.runtime_root / "round-analyses"

    def analysis_path(self, analysis_id: UUID | str) -> Path:
        """Return the final directory for one validated analysis ID."""

        return self.root / str(UUID(str(analysis_id)))

    def counterfactual_path(
        self,
        source_analysis_id: UUID | str,
        counterfactual_id: UUID | str,
    ) -> Path:
        """Return the final directory for one validated counterfactual ID."""

        return (
            self.analysis_path(source_analysis_id)
            / "counterfactuals"
            / str(UUID(str(counterfactual_id)))
        )

    def publish(
        self,
        analysis_id: UUID | str,
        input_bytes: bytes,
        result_bytes: bytes,
    ) -> StoredRoundAnalysisArtifacts:
        """Atomically publish exact input and result bytes as one directory."""

        analysis_uuid = UUID(str(analysis_id))
        if not isinstance(input_bytes, bytes) or not isinstance(result_bytes, bytes):
            raise TypeError("analysis artifact contents must be bytes.")
        destination = self.analysis_path(analysis_uuid)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"analysis artifact directory already exists: {destination}")

        staging: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"analysis artifact directory already exists: {destination}")
            staging = Path(tempfile.mkdtemp(prefix=f".{analysis_uuid}-", dir=self.root))
            input_file = self._write(staging / "input.json", input_bytes)
            result_file = self._write(staging / "result.json", result_bytes)
            self._rename(staging, destination)
            staging = None
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

        return StoredRoundAnalysisArtifacts(
            analysis_id=analysis_uuid,
            input=StoredRoundAnalysisArtifact(
                relative_path=f"round-analyses/{analysis_uuid}/input.json",
                byte_length=input_file[0],
                sha256=input_file[1],
            ),
            result=StoredRoundAnalysisArtifact(
                relative_path=f"round-analyses/{analysis_uuid}/result.json",
                byte_length=result_file[0],
                sha256=result_file[1],
            ),
        )

    def publish_counterfactual(
        self,
        source_analysis_id: UUID | str,
        counterfactual_id: UUID | str,
        request_bytes: bytes,
        input_bytes: bytes,
        result_bytes: bytes,
    ) -> StoredCounterfactualArtifacts:
        """Atomically publish one request, derived input, result, and digest manifest."""

        source_uuid = UUID(str(source_analysis_id))
        counterfactual_uuid = UUID(str(counterfactual_id))
        values = (request_bytes, input_bytes, result_bytes)
        if not all(isinstance(value, bytes) for value in values):
            raise TypeError("counterfactual artifact contents must be bytes.")
        destination = self.counterfactual_path(source_uuid, counterfactual_uuid)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"counterfactual artifact directory already exists: {destination}"
            )
        analysis_directory = self.analysis_path(source_uuid)
        if analysis_directory.is_symlink() or (
            analysis_directory.exists() and not analysis_directory.is_dir()
        ):
            raise OSError(f"analysis artifact directory is not usable: {analysis_directory}")

        staging: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(
                    f"counterfactual artifact directory already exists: {destination}"
                )
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{counterfactual_uuid}-",
                    dir=destination.parent,
                )
            )
            request_file = self._write(staging / "request.json", request_bytes)
            input_file = self._write(staging / "input.json", input_bytes)
            result_file = self._write(staging / "result.json", result_bytes)
            manifest = self._counterfactual_manifest(
                source_uuid,
                counterfactual_uuid,
                request_file,
                input_file,
                result_file,
            )
            self._write(staging / "manifest.json", manifest)
            self._rename(staging, destination)
            staging = None
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

        return StoredCounterfactualArtifacts(
            source_analysis_id=source_uuid,
            counterfactual_id=counterfactual_uuid,
            request=self._stored_counterfactual_artifact(
                source_uuid, counterfactual_uuid, "request.json", request_file
            ),
            input=self._stored_counterfactual_artifact(
                source_uuid, counterfactual_uuid, "input.json", input_file
            ),
            result=self._stored_counterfactual_artifact(
                source_uuid, counterfactual_uuid, "result.json", result_file
            ),
        )

    def read_counterfactual(
        self,
        source_analysis_id: UUID | str,
        counterfactual_id: UUID | str,
    ) -> StoredCounterfactualContents:
        """Read and verify one published counterfactual directory."""

        source_uuid = UUID(str(source_analysis_id))
        counterfactual_uuid = UUID(str(counterfactual_id))
        directory = self.counterfactual_path(source_uuid, counterfactual_uuid)
        if not directory.is_dir() or directory.is_symlink():
            raise FileNotFoundError(f"counterfactual artifacts are unavailable: {directory}")
        try:
            manifest_bytes = self._read_regular_file(directory / "manifest.json")
            manifest = self._parse_counterfactual_manifest(manifest_bytes)
            if manifest["source_analysis_id"] != str(source_uuid) or manifest[
                "counterfactual_id"
            ] != str(counterfactual_uuid):
                raise OSError("counterfactual manifest IDs do not match its directory")
            artifacts = {
                name: self._manifest_artifact(manifest, name)
                for name in ("request", "input", "result")
            }
            values = {
                name: self._read_and_verify_artifact(
                    directory / artifact.relative_path.rsplit("/", maxsplit=1)[-1], artifact
                )
                for name, artifact in artifacts.items()
            }
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
            raise OSError("counterfactual artifact manifest is invalid") from error
        return StoredCounterfactualContents(
            artifacts=StoredCounterfactualArtifacts(
                source_analysis_id=source_uuid,
                counterfactual_id=counterfactual_uuid,
                request=artifacts["request"],
                input=artifacts["input"],
                result=artifacts["result"],
            ),
            request_bytes=values["request"],
            input_bytes=values["input"],
            result_bytes=values["result"],
        )

    @staticmethod
    def _counterfactual_manifest(
        source_analysis_id: UUID,
        counterfactual_id: UUID,
        request_file: tuple[int, str],
        input_file: tuple[int, str],
        result_file: tuple[int, str],
    ) -> bytes:
        def entry(name: str, value: tuple[int, str]) -> dict[str, Any]:
            return {
                "relative_path": (
                    f"round-analyses/{source_analysis_id}/counterfactuals/"
                    f"{counterfactual_id}/{name}.json"
                ),
                "byte_length": value[0],
                "sha256": value[1],
            }

        return json.dumps(
            {
                "schema_version": COUNTERFACTUAL_MANIFEST_SCHEMA_VERSION,
                "source_analysis_id": str(source_analysis_id),
                "counterfactual_id": str(counterfactual_id),
                "artifacts": {
                    "request": entry("request", request_file),
                    "input": entry("input", input_file),
                    "result": entry("result", result_file),
                },
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @staticmethod
    def _stored_counterfactual_artifact(
        source_analysis_id: UUID,
        counterfactual_id: UUID,
        name: str,
        value: tuple[int, str],
    ) -> StoredRoundAnalysisArtifact:
        return StoredRoundAnalysisArtifact(
            relative_path=(
                f"round-analyses/{source_analysis_id}/counterfactuals/{counterfactual_id}/{name}"
            ),
            byte_length=value[0],
            sha256=value[1],
        )

    @staticmethod
    def _parse_counterfactual_manifest(raw: bytes) -> dict[str, Any]:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("manifest must be an object")
        if set(value) != {
            "schema_version",
            "source_analysis_id",
            "counterfactual_id",
            "artifacts",
        }:
            raise ValueError("manifest fields are invalid")
        if value["schema_version"] != COUNTERFACTUAL_MANIFEST_SCHEMA_VERSION:
            raise ValueError("manifest schema version is invalid")
        if not isinstance(value["source_analysis_id"], str) or not isinstance(
            value["counterfactual_id"], str
        ):
            raise ValueError("manifest IDs are invalid")
        UUID(value["source_analysis_id"])
        UUID(value["counterfactual_id"])
        if not isinstance(value["artifacts"], dict) or set(value["artifacts"]) != {
            "request",
            "input",
            "result",
        }:
            raise ValueError("manifest artifacts are invalid")
        return value

    @classmethod
    def _manifest_artifact(
        cls,
        manifest: dict[str, Any],
        name: str,
    ) -> StoredRoundAnalysisArtifact:
        raw = manifest["artifacts"][name]
        if not isinstance(raw, dict) or set(raw) != {"relative_path", "byte_length", "sha256"}:
            raise ValueError("manifest artifact fields are invalid")
        relative_path = raw["relative_path"]
        byte_length = raw["byte_length"]
        sha256 = raw["sha256"]
        expected_path = (
            f"round-analyses/{manifest['source_analysis_id']}/counterfactuals/"
            f"{manifest['counterfactual_id']}/{name}.json"
        )
        if relative_path != expected_path:
            raise ValueError("manifest artifact path is invalid")
        if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 0:
            raise ValueError("manifest artifact length is invalid")
        if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
            raise ValueError("manifest artifact digest is invalid")
        return StoredRoundAnalysisArtifact(
            relative_path=relative_path,
            byte_length=byte_length,
            sha256=sha256,
        )

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        if not path.is_file() or path.is_symlink():
            raise OSError(f"counterfactual artifact is unavailable: {path.name}")
        return path.read_bytes()

    @classmethod
    def _read_and_verify_artifact(
        cls,
        path: Path,
        artifact: StoredRoundAnalysisArtifact,
    ) -> bytes:
        value = cls._read_regular_file(path)
        if len(value) != artifact.byte_length or (
            hashlib.sha256(value).hexdigest() != artifact.sha256
        ):
            raise OSError(f"counterfactual artifact bytes failed verification: {path.name}")
        return value

    @staticmethod
    def _write(path: Path, value: bytes) -> tuple[int, str]:
        digest = hashlib.sha256(value).hexdigest()
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != value:
            raise OSError(f"published artifact bytes failed verification: {path.name}")
        return len(value), digest

    @staticmethod
    def _rename(source: Path, destination: Path) -> None:
        """Rename a complete staging directory on the same filesystem."""

        os.rename(source, destination)


__all__ = [
    "COUNTERFACTUAL_MANIFEST_SCHEMA_VERSION",
    "RoundAnalysisArtifactStorage",
    "StoredRoundAnalysisArtifact",
    "StoredRoundAnalysisArtifacts",
    "StoredCounterfactualArtifacts",
    "StoredCounterfactualContents",
]
