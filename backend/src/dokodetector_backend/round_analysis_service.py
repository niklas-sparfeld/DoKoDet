"""Queue and execute one local round-analysis worker."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING
from uuid import UUID

from doko_operations.counterfactual import (
    RoundCounterfactualRequest,
    canonical_counterfactual_bytes,
    derive_counterfactual_input,
    parse_round_counterfactual_request_bytes,
    recompute_counterfactual,
)
from doko_operations.round_reconstruction import (
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
    run_round_reconstruction_values,
)
from game_engine import canonical_json_bytes as canonical_engine_json_bytes
from game_engine import parse_reconstruction_input_bytes
from table_evidence_analyzer import TableEvidenceAnalyzer

from dokodetector_backend.analyzer_runner import AnalyzerRunner
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.intake_contract import (
    EvidencePackageLineage,
    IntakeContractError,
    parse_evidence_package_lineage,
)
from dokodetector_backend.logging_config import log_event
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
from dokodetector_backend.round_analysis_storage import (
    RoundAnalysisArtifactStorage,
    StoredCounterfactualArtifacts,
    StoredCounterfactualContents,
)
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


class RoundCounterfactualConflict(ValueError):
    """A counterfactual ID is already stored with different request content."""


class RoundCounterfactualNotFound(LookupError):
    """The requested counterfactual artifact directory does not exist."""


class RoundCounterfactualIntegrityError(RuntimeError):
    """A stored counterfactual artifact set failed validation."""


@dataclass(frozen=True, slots=True)
class ValidatedRoundAnalysisInput:
    """The immutable packages selected by one validated analysis request."""

    request: RoundAnalysisCreateRequest
    packages: tuple[StoredPackage, ...]


@dataclass(frozen=True, slots=True)
class StoredRoundCounterfactual:
    """A parsed counterfactual response backed by immutable runtime artifacts."""

    request: RoundCounterfactualRequest
    artifacts: StoredCounterfactualArtifacts
    result: RoundReconstructionRunResult


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
        self._queue: asyncio.Queue[tuple[UUID, str] | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._counterfactual_lock = Lock()

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
        _log_worker_event("round_analysis_worker_started", queue_depth=self._queue.qsize())

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
            _log_worker_event("round_analysis_worker_stopped", queue_depth=self._queue.qsize())

    def enqueue(self, analysis_id: UUID, request_id: str) -> None:
        """Queue one newly created analysis for the lifespan worker."""

        self._queue.put_nowait((analysis_id, request_id))
        log_event(
            LOGGER,
            logging.DEBUG,
            "round_analysis_queued",
            request_id=request_id,
            analysis_id=str(analysis_id),
            queue_depth=self._queue.qsize(),
        )

    def run_synchronously(self, analysis_id: UUID, request_id: str) -> None:
        """Execute one analysis immediately for the test-only API hook."""

        self._run_one(analysis_id, request_id)

    async def _worker_loop(self) -> None:
        while True:
            queued = await self._queue.get()
            try:
                if queued is None:
                    return
                analysis_id, request_id = queued
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "round_analysis_worker_dequeued",
                    request_id=request_id,
                    analysis_id=str(analysis_id),
                    queue_depth=self._queue.qsize(),
                )
                await asyncio.to_thread(self._run_one, analysis_id, request_id)
            finally:
                self._queue.task_done()

    def _run_one(self, analysis_id: UUID, request_id: str) -> None:
        analysis = self.repository.get(analysis_id)
        if analysis is None or analysis.state in {"complete", "failed"}:
            return
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
            selected = self.validate_request(request)
            log_event(
                LOGGER,
                logging.DEBUG,
                "round_analysis_input_validated",
                request_id=request_id,
                analysis_id=str(analysis_id),
                recording_id=selected.request.recording_id,
                package_count=len(selected.packages),
            )
            updated = self.repository.update_progress(
                analysis_id,
                state="analyzing_evidence",
                completed=0,
            )
            _log_state_change(analysis, updated, request_id)
            analysis = updated
            observations: list[StoredTableObservation] = []
            for index, package in enumerate(selected.packages, start=1):
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "round_analysis_package_started",
                    **_analysis_context(analysis, request_id),
                    package_id=str(package.package_id),
                    package_index=index,
                    total_packages=len(selected.packages),
                )
                observation = self.analyzer_runner.run_once(package.package_id)
                if observation is None:
                    raise RuntimeError("The selected evidence package could not be analyzed.")
                observations.append(observation)
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "round_analysis_package_completed",
                    **_analysis_context(analysis, request_id),
                    package_id=str(package.package_id),
                    package_index=index,
                    total_packages=len(selected.packages),
                    analyzer=observation.analyzer_name,
                    analyzer_version=observation.analyzer_version,
                    analysis_status=observation.status,
                )
                analysis = self.repository.update_progress(
                    analysis_id,
                    state="analyzing_evidence",
                    completed=index,
                )

            updated = self.repository.update_progress(
                analysis_id,
                state="reconstructing",
                completed=len(observations),
            )
            _log_state_change(analysis, updated, request_id)
            analysis = updated
            log_event(
                LOGGER,
                logging.DEBUG,
                "round_analysis_reconstruction_started",
                **_analysis_context(analysis, request_id),
                observation_count=len(observations),
            )
            result, artifacts = self._run_reconstruction(selected, observations)
            log_event(
                LOGGER,
                logging.DEBUG,
                "round_analysis_reconstruction_completed",
                **_analysis_context(analysis, request_id),
                observation_count=len(observations),
                result_status=result.status,
                hypothesis_count=len(result.hypotheses),
            )
            published = self.artifact_storage.publish(
                analysis_id,
                artifacts[0],
                artifacts[1],
            )
            log_event(
                LOGGER,
                logging.DEBUG,
                "round_analysis_artifacts_published",
                **_analysis_context(analysis, request_id),
                input_artifact_id=published.input.relative_path,
                input_byte_length=published.input.byte_length,
                input_sha256=published.input.sha256,
                result_artifact_id=published.result.relative_path,
                result_byte_length=published.result.byte_length,
                result_sha256=published.result.sha256,
            )
            completed = self.repository.mark_complete(
                analysis_id,
                result_status=result.status,
                result_json=artifacts[1].decode("utf-8"),
                input_artifact_id=published.input.relative_path,
                input_artifact_sha256=published.input.sha256,
                result_artifact_id=published.result.relative_path,
                result_artifact_sha256=published.result.sha256,
            )
            log_event(
                LOGGER,
                logging.INFO,
                "round_analysis_completed",
                **_analysis_fields(completed, request_id),
                state="complete",
                result_status=result.status,
            )
        except Exception as error:
            failure_info = _exception_info(error)
            try:
                failed = self.repository.mark_failed(analysis_id, ANALYSIS_WORKER_FAILURE)
            except (RoundAnalysisNotFound, ValueError) as persistence_error:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "round_analysis_failure_persist_failed",
                    exc_info=_exception_info(persistence_error),
                    **_analysis_fields(analysis, request_id),
                    cause=type(error).__name__,
                )
            else:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "round_analysis_failed",
                    exc_info=failure_info,
                    **_analysis_fields(failed, request_id),
                    state="failed",
                    error=failed.error,
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

    def create_counterfactual(
        self,
        analysis_id: UUID,
        request: RoundCounterfactualRequest,
    ) -> StoredRoundCounterfactual:
        """Synchronously derive and atomically publish one counterfactual."""

        if request.source_analysis_id != analysis_id:
            raise RoundCounterfactualConflict(
                "source_analysis_id must match the analysis ID in the request path."
            )
        with self._counterfactual_lock:
            analysis, verified = self._load_verified_source(analysis_id)
            request_bytes = canonical_counterfactual_bytes(request)
            existing = self._read_existing_counterfactual(
                analysis_id,
                request.counterfactual_id,
                analysis,
                verified.input,
                verified.result,
            )
            if existing is not None:
                if existing.request_bytes != request_bytes:
                    raise RoundCounterfactualConflict(
                        "The counterfactual ID is already stored with different request content."
                    )
                return self._counterfactual_from_contents(existing)

            if (
                request.source_input_sha256 != analysis.input_artifact_sha256
                or request.source_result_sha256 != analysis.result_artifact_sha256
            ):
                raise ValueError("counterfactual source artifact hashes do not match the analysis.")
            try:
                run = recompute_counterfactual(request, verified.input, verified.result)
                published = self.artifact_storage.publish_counterfactual(
                    analysis_id,
                    request.counterfactual_id,
                    request_bytes,
                    run.input_bytes,
                    run.result_bytes,
                )
            except FileExistsError as error:
                existing = self._read_existing_counterfactual(
                    analysis_id,
                    request.counterfactual_id,
                    analysis,
                    verified.input,
                    verified.result,
                )
                if existing is None:
                    raise
                if existing.request_bytes != request_bytes:
                    raise RoundCounterfactualConflict(
                        "The counterfactual ID is already stored with different request content."
                    ) from error
                return self._counterfactual_from_contents(existing)
            return StoredRoundCounterfactual(
                request=request,
                artifacts=published,
                result=run.result,
            )

    def get_counterfactual(
        self,
        analysis_id: UUID,
        counterfactual_id: UUID,
    ) -> StoredRoundCounterfactual:
        """Read one immutable counterfactual after validating its source analysis."""

        analysis, verified = self._load_verified_source(analysis_id)
        contents = self._read_existing_counterfactual(
            analysis_id,
            counterfactual_id,
            analysis,
            verified.input,
            verified.result,
        )
        if contents is None:
            raise RoundCounterfactualNotFound("The counterfactual was not found.")
        return self._counterfactual_from_contents(contents)

    def _load_verified_source(self, analysis_id: UUID):
        analysis = self.repository.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        verified = self.timeline_projector.load_verified_artifacts(analysis)
        return analysis, verified

    def _read_existing_counterfactual(
        self,
        analysis_id: UUID,
        counterfactual_id: UUID,
        analysis: StoredRoundAnalysis,
        source_input,
        source_result: RoundReconstructionRunResult,
    ) -> StoredCounterfactualContents | None:
        path = self.artifact_storage.counterfactual_path(analysis_id, counterfactual_id)
        if not path.exists() and not path.is_symlink():
            return None
        try:
            contents = self.artifact_storage.read_counterfactual(analysis_id, counterfactual_id)
            request = parse_round_counterfactual_request_bytes(contents.request_bytes)
            input_value = parse_reconstruction_input_bytes(contents.input_bytes)
            result = RoundReconstructionRunResult.from_mapping(
                json_loads(contents.result_bytes.decode("utf-8"))
            )
            if (
                request.source_analysis_id != analysis_id
                or request.counterfactual_id != counterfactual_id
                or request.source_input_sha256 != analysis.input_artifact_sha256
                or request.source_result_sha256 != analysis.result_artifact_sha256
                or result.run_id != str(counterfactual_id)
                or contents.request_bytes != canonical_counterfactual_bytes(request)
            ):
                raise ValueError("counterfactual artifact identity is invalid")
            expected_input = derive_counterfactual_input(request, source_input)
            if input_value != expected_input or contents.input_bytes != canonical_engine_json_bytes(
                expected_input
            ):
                raise ValueError("counterfactual input does not match its request")
            retained_ids = {item.observation_id for item in expected_input.observations}
            expected_sources = tuple(
                record for record in source_result.sources if record.observation_id in retained_ids
            )
            if result.search != source_result.search or result.sources != expected_sources:
                raise ValueError("counterfactual result sources do not match its request")
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise RoundCounterfactualIntegrityError(
                "The stored counterfactual artifacts failed integrity validation."
            ) from error
        return contents

    @staticmethod
    def _counterfactual_from_contents(
        contents: StoredCounterfactualContents,
    ) -> StoredRoundCounterfactual:
        try:
            request = parse_round_counterfactual_request_bytes(contents.request_bytes)
            result = RoundReconstructionRunResult.from_mapping(
                json_loads(contents.result_bytes.decode("utf-8"))
            )
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise RoundCounterfactualIntegrityError(
                "The stored counterfactual artifacts failed integrity validation."
            ) from error
        return StoredRoundCounterfactual(
            request=request,
            artifacts=contents.artifacts,
            result=result,
        )

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


def _analysis_context(analysis: StoredRoundAnalysis, request_id: str) -> dict[str, object]:
    """Return stable identifiers for one analysis trace event."""

    return {
        "request_id": request_id,
        "analysis_id": str(analysis.analysis_id),
    }


def _analysis_fields(analysis: StoredRoundAnalysis, request_id: str) -> dict[str, object]:
    """Return stable identifiers and bounded progress for one lifecycle event."""

    return {
        **_analysis_context(analysis, request_id),
        "recording_id": analysis.recording_id,
        "round_id": analysis.round_id,
        "session_id": str(analysis.session_id),
        "completed_evidence_packages": analysis.completed_evidence_packages,
        "total_evidence_packages": analysis.total_evidence_packages,
    }


def _log_state_change(
    previous: StoredRoundAnalysis,
    current: StoredRoundAnalysis,
    request_id: str,
) -> None:
    """Log only meaningful non-terminal state transitions at INFO."""

    if previous.state == current.state:
        return
    log_event(
        LOGGER,
        logging.INFO,
        "round_analysis_state_changed",
        **_analysis_fields(current, request_id),
        previous_state=previous.state,
        state=current.state,
    )


def _log_worker_event(event: str, *, queue_depth: int) -> None:
    """Log process-level worker lifecycle events."""

    log_event(LOGGER, logging.INFO, event, queue_depth=queue_depth)


def _exception_info(
    error: BaseException,
) -> tuple[type[BaseException], BaseException, object] | None:
    """Return traceback information for one failed worker operation."""

    if error.__traceback__ is None:
        return None
    return type(error), error, error.__traceback__


__all__ = [
    "ANALYSIS_WORKER_FAILURE",
    "RoundAnalysisService",
    "RoundAnalysisValidationError",
    "ValidatedRoundAnalysisInput",
]
