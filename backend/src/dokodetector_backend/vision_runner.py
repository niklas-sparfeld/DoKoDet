"""Synchronous local orchestration for stored evidence and a vision detector."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError
from vision_detector import (
    SCRIPTED_DETECTOR_NAME,
    ScriptedVisionDetector,
    VisionDetectionResult,
    VisionDetector,
    VisionSession,
    canonical_json_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.persistence import VisionResultPersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    StoredVisionResult,
    create_database_engine,
    upgrade_database,
)
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.vision_adapter import load_vision_evidence

if TYPE_CHECKING:
    from dokodetector_backend.repository import StoredPackage


class VisionRunnerError(RuntimeError):
    """The local detector pipeline could not produce a result."""


class VisionRunner:
    """Run one configured detector synchronously for accepted evidence packages."""

    def __init__(
        self,
        repository: EvidenceRepository,
        storage: EvidenceStorage,
        detector: VisionDetector,
        *,
        detector_name: str | None = None,
        detector_version: str | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.detector = detector
        self.detector_name = detector_name or getattr(detector, "name", None)
        self.detector_version = detector_version or getattr(detector, "version", None)
        if not self.detector_name or not self.detector_version:
            raise ValueError("detector name and version are required for result selection.")
        self.result_persister = VisionResultPersister(repository, storage)

    def run_once(self, package_id: UUID | str | None = None) -> StoredVisionResult | None:
        """Run the detector for one explicit or pending package."""

        package = self._select_package(package_id)
        if package is None:
            return None

        existing = self.repository.get_vision_result_for_detector(
            package.package_id,
            self.detector_name,
            self.detector_version,
        )
        if existing is not None:
            return existing

        evidence = load_vision_evidence(package, self.storage)
        try:
            detected = self.detector.detect(evidence)
        except Exception as error:
            raise VisionRunnerError("The detector invocation failed.") from error
        if not isinstance(detected, VisionDetectionResult):
            raise VisionRunnerError("The detector did not return a valid vision result.")
        if (
            detected.detector.name != self.detector_name
            or detected.detector.version != self.detector_version
        ):
            raise VisionRunnerError(
                "The detector result identity does not match its configuration."
            )

        result = self._normalize_result(detected, package)
        result_bytes = canonical_json_bytes(result)
        return self.result_persister.persist(result, result_bytes)

    def run_all(self) -> tuple[StoredVisionResult, ...]:
        """Run the detector once for every currently pending package."""

        results: list[StoredVisionResult] = []
        while (result := self.run_once()) is not None:
            results.append(result)
        return tuple(results)

    def _select_package(self, package_id: UUID | str | None) -> StoredPackage | None:
        if package_id is not None:
            package = self.repository.get_package(package_id)
            if package is None:
                raise VisionRunnerError("The evidence package was not found.")
            return package
        return self.repository.get_pending_package(self.detector_name, self.detector_version)

    def _normalize_result(
        self,
        detected: VisionDetectionResult,
        package: StoredPackage,
    ) -> VisionDetectionResult:
        payload = detected.model_dump(mode="python")
        payload["package_id"] = package.package_id
        payload["session"] = VisionSession(
            session_id=package.session_id,
            event_sequence=package.event_sequence,
        )
        try:
            return VisionDetectionResult.model_validate(payload)
        except ValidationError as error:
            raise VisionRunnerError("The detector result failed validation.") from error


def build_scripted_runner(settings: Settings) -> VisionRunner:
    """Build the configured local scripted-detector runner."""

    if settings.vision_detector_name != SCRIPTED_DETECTOR_NAME:
        raise ValueError("Only the scripted detector is configured for this local PoC.")
    detector = ScriptedVisionDetector(
        mapping_path=settings.vision_detector_mapping_path,
        version=settings.vision_detector_version,
    )
    backend_root = Path(__file__).resolve().parents[2]
    upgrade_database(backend_root, settings.database_url)
    repository = EvidenceRepository(create_database_engine(settings.database_url))
    storage = EvidenceStorage(settings.evidence_root)
    return VisionRunner(
        repository,
        storage,
        detector,
        detector_name=SCRIPTED_DETECTOR_NAME,
        detector_version=settings.vision_detector_version,
    )


__all__ = ["VisionRunner", "VisionRunnerError", "build_scripted_runner"]
