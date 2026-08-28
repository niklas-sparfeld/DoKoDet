"""Synchronous local orchestration for stored evidence and an analyzer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError
from table_evidence_analyzer import (
    TableEvidenceAnalyzer,
    TableObservation,
    canonical_json_bytes,
)

from dokodetector_backend.analyzer_adapter import load_analyzer_evidence
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.persistence import TableObservationPersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    StoredTableObservation,
)
from dokodetector_backend.storage import EvidenceStorage

if TYPE_CHECKING:
    from dokodetector_backend.repository import StoredPackage


class AnalyzerRunnerError(RuntimeError):
    """The local analyzer pipeline could not produce an observation."""


class AnalyzerRunner:
    """Run one configured analyzer synchronously for accepted evidence packages."""

    def __init__(
        self,
        repository: EvidenceRepository,
        storage: EvidencePackageStorage,
        analyzer: TableEvidenceAnalyzer,
        *,
        observation_storage: EvidenceStorage,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.analyzer = analyzer
        self.analyzer_name = getattr(analyzer, "name", None)
        self.analyzer_version = getattr(analyzer, "version", None)
        if not self.analyzer_name or not self.analyzer_version:
            raise ValueError("analyzer name and version are required for observation selection.")
        self.observation_persister = TableObservationPersister(repository, observation_storage)

    def run_once(self, package_id: UUID | str | None = None) -> StoredTableObservation | None:
        """Run the analyzer for one explicit or pending package."""

        package = self._select_package(package_id)
        if package is None:
            return None

        existing = self.repository.get_table_observation_for_analyzer(
            package.package_id,
            self.analyzer_name,
            self.analyzer_version,
        )
        if existing is not None:
            return existing

        evidence = load_analyzer_evidence(package, self.storage)
        try:
            observation = self.analyzer.analyze(evidence)
        except Exception as error:
            raise AnalyzerRunnerError("The analyzer invocation failed.") from error
        if not isinstance(observation, TableObservation):
            raise AnalyzerRunnerError("The analyzer did not return a valid table observation.")
        if (
            observation.analyzer.name != self.analyzer_name
            or observation.analyzer.version != self.analyzer_version
        ):
            raise AnalyzerRunnerError("The observation identity does not match its configuration.")

        observation = self._normalize_observation(observation, package)
        observation_bytes = canonical_json_bytes(observation)
        return self.observation_persister.persist(observation, observation_bytes)

    def run_all(self) -> tuple[StoredTableObservation, ...]:
        """Run the analyzer once for every currently pending package."""

        observations: list[StoredTableObservation] = []
        while (observation := self.run_once()) is not None:
            observations.append(observation)
        return tuple(observations)

    def _select_package(self, package_id: UUID | str | None) -> StoredPackage | None:
        if package_id is not None:
            package = self.repository.get_package(package_id)
            if package is None:
                raise AnalyzerRunnerError("The evidence package was not found.")
            return package
        return self.repository.get_pending_package(self.analyzer_name, self.analyzer_version)

    def _normalize_observation(
        self,
        observation: TableObservation,
        package: StoredPackage,
    ) -> TableObservation:
        payload = observation.model_dump(mode="python", exclude_none=True)
        payload["source"] = {
            **payload["source"],
            "package_id": str(package.package_id),
        }
        payload["session"] = {
            "session_id": str(package.session_id),
            "event_sequence": package.event_sequence,
        }
        try:
            return TableObservation.model_validate(payload)
        except ValidationError as error:
            raise AnalyzerRunnerError("The analyzer observation failed validation.") from error


__all__ = ["AnalyzerRunner", "AnalyzerRunnerError"]
