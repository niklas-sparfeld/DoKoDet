"""Atomic runtime storage for round-analysis input and result artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
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


class RoundAnalysisArtifactStorage:
    """Publish immutable analysis artifacts below a disposable runtime root."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.root = self.runtime_root / "round-analyses"

    def analysis_path(self, analysis_id: UUID | str) -> Path:
        """Return the final directory for one validated analysis ID."""

        return self.root / str(UUID(str(analysis_id)))

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
    "RoundAnalysisArtifactStorage",
    "StoredRoundAnalysisArtifact",
    "StoredRoundAnalysisArtifacts",
]
