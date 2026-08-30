"""Queue and execute one local round-analysis worker."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from doko_operations.round_reconstruction import (
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
    run_round_reconstruction_values,
)
from table_evidence_analyzer import TableEvidenceAnalyzer

from dokodetector_backend.analyzer_runner import AnalyzerRunner
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.intake_contract import (
    EvidencePackageLineage,
    IntakeContractError,
    parse_evidence_package_lineage,
)
from dokodetector_backend.repository import (
    EvidenceRepository,
    RoundAnalysisNotFound,
    RoundAnalysisRepository,
    StoredRoundAnalysis,
    StoredTableObservation,
)
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.round_analysis_contract import (
    RoundAnalysisCreateRequest,
    RoundAnalysisResult,
    RoundAnalysisStatus,
    parse_round_analysis_create_request_bytes,
)
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.round_analysis_timeline import (
    RoundAnalysisTimeline,
    RoundAnalysisTimelineProjector,
    TimelineFrameFile,
)
from dokodetector_backend.storage import EvidenceStorage

if TYPE_CHECKING:
    from dokodetector_backend.repository import StoredPackage


LOGGER = logging.getLogger(__name__)
ANALYSIS_WORKER_FAILURE = "The round analysis could not be completed."


class RoundAnalysisValidationError(ValueError):
    """The selected recording and evidence do not form a valid analysis input."""


@dataclass(frozen=True, slots=True)
class ValidatedRoundAnalysisInput:
    """The immutable packages selected by one validated analysis request."""

    request: RoundAnalysisCreateRequest
    packages: tuple[StoredPackage, ...]


class RoundAnalysisService:
    """Own the process-local queue and execute analyses one at a time."""

    def __init__(
        self,
        repository: RoundAnalysisRepository,
        evidence_repository: EvidenceRepository,
        package_storage: EvidencePackageStorage,
        evidence_storage: EvidenceStorage,
        artifact_storage: RoundAnalysisArtifactStorage,
        repository_bundle_repository: RepositoryBundleRepository,
        analyzer: TableEvidenceAnalyzer,
    ) -> None:
        self.repository = repository
        self.evidence_repository = evidence_repository
        self.package_storage = package_storage
        self.evidence_storage = evidence_storage
        self.artifact_storage = artifact_storage
        self.repository_bundle_repository = repository_bundle_repository
        self.analyzer_runner = AnalyzerRunner(
            evidence_repository,
            package_storage,
            analyzer,
            observation_storage=evidence_storage,
        )
        self.timeline_projector = RoundAnalysisTimelineProjector(
            evidence_repository,
            package_storage,
            evidence_storage,
            artifact_storage,
        )
        self._queue: asyncio.Queue[UUID | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def worker_task(self) -> asyncio.Task[None] | None:
        """Return the lifespan-owned worker task for lifecycle tests."""

        return self._worker_task

    def validate_request(self, request: RoundAnalysisCreateRequest) -> ValidatedRoundAnalysisInput:
        """Validate stored recording, package lineage, and shared session identity."""

        recording = self.repository_bundle_repository.get(request.recording_id)
        if recording is None:
            raise RoundAnalysisValidationError("The recording bundle is not stored.")
        expected_session_id = str(request.session_id)
        if recording.session_id != expected_session_id:
            raise RoundAnalysisValidationError(
                "The recording bundle session does not match the analysis session."
            )

        packages: list[StoredPackage] = []
        for package_id in request.evidence_package_ids:
            package = self.evidence_repository.get_package(package_id)
            if package is None:
                raise RoundAnalysisValidationError(
                    f"The evidence package {package_id} is not stored."
                )
            if package.session_id != request.session_id:
                raise RoundAnalysisValidationError(
                    "All evidence packages must use the analysis session."
                )
            lineage = self._read_lineage(package)
            if lineage.parent_recording_id != request.recording_id:
                raise RoundAnalysisValidationError(
                    f"The evidence package {package_id} is not linked to the recording."
                )
            if lineage.session_id != expected_session_id:
                raise RoundAnalysisValidationError(
                    "All evidence package lineage records must use the analysis session."
                )
            packages.append(package)
        return ValidatedRoundAnalysisInput(request=request, packages=tuple(packages))

    async def start(self) -> None:
        """Start the one worker task after app resources are ready."""

        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker_loop(), name="round-analysis-worker")

    async def stop(self) -> None:
        """Drain queued work and wait for the worker to stop cleanly."""

        task = self._worker_task
        if task is None:
            return
        await self._queue.put(None)
        try:
            await task
        finally:
            self._worker_task = None

    def enqueue(self, analysis_id: UUID) -> None:
        """Queue one newly created analysis for the lifespan worker."""

        self._queue.put_nowait(analysis_id)

    def run_synchronously(self, analysis_id: UUID) -> None:
        """Execute one analysis immediately for the test-only API hook."""

        self._run_one(analysis_id)

    async def _worker_loop(self) -> None:
        while True:
            analysis_id = await self._queue.get()
            try:
                if analysis_id is None:
                    return
                await asyncio.to_thread(self._run_one, analysis_id)
            finally:
                self._queue.task_done()

    def _run_one(self, analysis_id: UUID) -> None:
        analysis = self.repository.get(analysis_id)
        if analysis is None or analysis.state in {"complete", "failed"}:
            return
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
            selected = self.validate_request(request)
            self.repository.update_progress(
                analysis_id,
                state="analyzing_evidence",
                completed=0,
            )
            observations: list[StoredTableObservation] = []
            for index, package in enumerate(selected.packages, start=1):
                observation = self.analyzer_runner.run_once(package.package_id)
                if observation is None:
                    raise RuntimeError("The selected evidence package could not be analyzed.")
                observations.append(observation)
                self.repository.update_progress(
                    analysis_id,
                    state="analyzing_evidence",
                    completed=index,
                )

            self.repository.update_progress(
                analysis_id,
                state="reconstructing",
                completed=len(observations),
            )
            result, artifacts = self._run_reconstruction(selected, observations)
            published = self.artifact_storage.publish(
                analysis_id,
                artifacts[0],
                artifacts[1],
            )
            self.repository.mark_complete(
                analysis_id,
                result_status=result.status,
                result_json=artifacts[1].decode("utf-8"),
                input_artifact_id=published.input.relative_path,
                input_artifact_sha256=published.input.sha256,
                result_artifact_id=published.result.relative_path,
                result_artifact_sha256=published.result.sha256,
            )
        except Exception:
            LOGGER.exception("round_analysis_failed analysis_id=%s", analysis_id)
            try:
                self.repository.mark_failed(analysis_id, ANALYSIS_WORKER_FAILURE)
            except (RoundAnalysisNotFound, ValueError):
                LOGGER.exception(
                    "round_analysis_failure_persist_failed analysis_id=%s", analysis_id
                )

    def _run_reconstruction(
        self,
        selected: ValidatedRoundAnalysisInput,
        observations: list[StoredTableObservation],
    ) -> tuple[RoundReconstructionRunResult, tuple[bytes, bytes]]:
        request = selected.request
        observation_paths = tuple(observation.relative_path for observation in observations)
        source_paths = tuple(
            self.evidence_storage.root / relative_path for relative_path in observation_paths
        )
        reconstruction_request = RoundReconstructionRunRequest(
            run_id=str(request.analysis_id),
            round_setup=request.round_setup.to_shared(),
            observation_paths=observation_paths,
            search=request.search.to_shared(),
            output_root=".",
        )
        self.artifact_storage.runtime_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{request.analysis_id}-", dir=self.artifact_storage.runtime_root
        ) as scratch_root:
            artifacts = run_round_reconstruction_values(
                reconstruction_request,
                source_paths,
                scratch_root,
            )
            return (
                artifacts.result,
                (artifacts.input_path.read_bytes(), artifacts.result_path.read_bytes()),
            )

    def status(self, analysis_id: UUID) -> RoundAnalysisStatus:
        """Convert one durable row to the public status document."""

        analysis = self.repository.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        result = self._result_from_analysis(analysis)
        return RoundAnalysisStatus(
            analysis_id=analysis.analysis_id,
            recording_id=analysis.recording_id,
            round_id=analysis.round_id,
            session_id=analysis.session_id,
            state=analysis.state,  # type: ignore[arg-type]
            total_evidence_packages=analysis.total_evidence_packages,
            completed_evidence_packages=analysis.completed_evidence_packages,
            result=result,
            error=analysis.error,
            created_at=analysis.created_at,
            started_at=analysis.started_at,
            completed_at=analysis.completed_at,
        )

    def timeline(self, analysis_id: UUID) -> RoundAnalysisTimeline:
        """Return the verified immutable timeline for one completed analysis."""

        analysis = self.repository.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        return self.timeline_projector.project(analysis)

    def frame(self, analysis_id: UUID, package_id: UUID, part_name: str) -> TimelineFrameFile:
        """Return one verified frame owned by one completed analysis."""

        analysis = self.repository.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        return self.timeline_projector.frame(analysis, package_id, part_name)

    def _result_from_analysis(self, analysis: StoredRoundAnalysis) -> RoundAnalysisResult | None:
        if analysis.state != "complete":
            return None
        if (
            analysis.result_json is None
            or analysis.result_status is None
            or analysis.input_artifact_id is None
            or analysis.input_artifact_sha256 is None
            or analysis.result_artifact_id is None
            or analysis.result_artifact_sha256 is None
        ):
            raise RuntimeError("The stored round analysis result is incomplete.")
        result = RoundReconstructionRunResult.from_mapping(json_loads(analysis.result_json))
        return RoundAnalysisResult(
            analysis_id=analysis.analysis_id,
            terminal_status="complete",
            reconstruction_status=result.status,
            hypotheses=[item.to_mapping() for item in result.hypotheses],
            focused_decisions=[item.to_mapping() for item in result.focused_decisions],
            diagnostics=result.diagnostics.to_mapping(),
            input_artifact_id=analysis.input_artifact_id,
            input_artifact_sha256=analysis.input_artifact_sha256,
            result_artifact_id=analysis.result_artifact_id,
            result_artifact_sha256=analysis.result_artifact_sha256,
        )

    def _read_lineage(self, package: StoredPackage) -> EvidencePackageLineage:
        path = self.package_storage.package_path(package.package_id) / "lineage.json"
        try:
            return parse_evidence_package_lineage(path.read_bytes())
        except (OSError, IntakeContractError) as error:
            raise RoundAnalysisValidationError(
                "The stored evidence package lineage is invalid."
            ) from error


def json_loads(value: str) -> dict[str, object]:
    """Decode stored result JSON without accepting non-object payloads."""

    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("stored result JSON must be an object")
    return payload


__all__ = [
    "ANALYSIS_WORKER_FAILURE",
    "RoundAnalysisService",
    "RoundAnalysisValidationError",
    "ValidatedRoundAnalysisInput",
]
