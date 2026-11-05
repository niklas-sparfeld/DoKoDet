"""Validate round-analysis inputs and execute managed analysis jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from doko_operations.counterfactual import (
    RoundCounterfactualRequest,
    canonical_counterfactual_bytes,
    derive_counterfactual_input,
    parse_round_counterfactual_request_bytes,
    recompute_counterfactual,
)
from doko_operations.pipeline_data import RecordingVideoSource
from doko_operations.round_reconstruction_contract import (
    RoundReconstructionRunRequest,
    RoundReconstructionRunResult,
)
from doko_operations.round_reconstruction_execution import (
    run_round_reconstruction_values,
)
from game_engine import canonical_json_bytes as canonical_engine_json_bytes
from game_engine import parse_reconstruction_input_bytes
from table_evidence_analyzer import TableEvidenceAnalyzer, TableObservation
from table_evidence_analyzer.pipeline_data import (
    TableObservationData,
    canonical_json_bytes,
    canonical_table_observation_data_bytes,
    parse_table_observation_data_bytes,
)

from dokodetector_backend.analyzer_runner import AnalyzerRunner
from dokodetector_backend.evidence_package_store import EvidencePackageStore
from dokodetector_backend.intake_contract import (
    EvidencePackageLineage,
    IntakeContractError,
    parse_evidence_package_lineage,
    parse_source_record,
)
from dokodetector_backend.job_store import Job, JobCancelled, JobManager
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineSelectionStore,
    StoredPipelineRevision,
)
from dokodetector_backend.recording_bundle_store import (
    RecordingBundleStore,
    StoredRecordingBundle,
)
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_contract import (
    AnalysisRoundContext,
    AnalysisRoundRuleset,
    AnalysisRoundSetup,
    AnalysisSearchLimits,
    RoundAnalysisCreateRequest,
    RoundAnalysisResult,
    RoundAnalysisStatus,
    canonical_analysis_request_sha256,
    parse_round_analysis_create_request_bytes,
)
from dokodetector_backend.round_analysis_storage import (
    RoundAnalysisArtifactStorage,
    StoredCounterfactualArtifacts,
    StoredCounterfactualContents,
)
from dokodetector_backend.round_analysis_store import (
    RoundAnalysisNotFound,
    RoundAnalysisStore,
)
from dokodetector_backend.round_analysis_timeline import (
    RoundAnalysisTimeline,
    RoundAnalysisTimelineProjector,
    TimelineFrameFile,
)
from dokodetector_backend.stored_models import (
    StoredPackage,
    StoredRoundAnalysis,
    StoredTableObservation,
)
from dokodetector_backend.table_observation_store import TableObservationStore

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
    pipeline_revision: StoredPipelineRevision | None = None


@dataclass(frozen=True, slots=True)
class RecordingCatalogEntry:
    """Durable recording metadata and the analyses attached to it."""

    recording: StoredRecordingBundle
    evidence_package_ids: tuple[UUID, ...]
    analyses: tuple[StoredRoundAnalysis, ...]
    round_id: str
    can_start_analysis: bool
    analysis_blocker: str | None


@dataclass(frozen=True, slots=True)
class StoredRoundCounterfactual:
    """A parsed counterfactual response backed by immutable runtime artifacts."""

    request: RoundCounterfactualRequest
    artifacts: StoredCounterfactualArtifacts
    result: RoundReconstructionRunResult


class RoundAnalysisService:
    """Validate immutable analysis inputs and publish round-analysis results."""

    def __init__(
        self,
        store: RoundAnalysisStore,
        package_store: EvidencePackageStore,
        observation_store: TableObservationStore,
        artifact_storage: RoundAnalysisArtifactStorage,
        recording_bundle_store: RecordingBundleStore,
        repository_bundle_storage: RepositoryBundleStorage,
        analyzer: TableEvidenceAnalyzer,
        pipeline_revision_store: PipelineRevisionStore | None = None,
        pipeline_selection_store: PipelineSelectionStore | None = None,
        pipeline_lineage_writer: Any | None = None,
    ) -> None:
        self.store = store
        self.package_store = package_store
        self.observation_store = observation_store
        self.package_storage = package_store.storage
        self.evidence_storage = observation_store.storage
        self.artifact_storage = artifact_storage
        self.recording_bundle_store = recording_bundle_store
        self.repository_bundle_storage = repository_bundle_storage
        self.pipeline_revision_store = pipeline_revision_store
        self.pipeline_selection_store = pipeline_selection_store
        self.pipeline_lineage_writer = pipeline_lineage_writer
        self.analyzer_runner = AnalyzerRunner(
            package_store,
            analyzer,
            observation_store=observation_store,
        )
        self.timeline_projector = RoundAnalysisTimelineProjector(
            package_store,
            observation_store,
            artifact_storage,
        )
        self._counterfactual_lock = Lock()

    def validate_request(self, request: RoundAnalysisCreateRequest) -> ValidatedRoundAnalysisInput:
        """Validate stored recording and the immutable input selected by the request."""

        recording = self.recording_bundle_store.get(request.recording_id)
        if recording is None:
            raise RoundAnalysisValidationError("The recording bundle is not stored.")
        expected_session_id = str(request.session_id)
        if recording.session_id != expected_session_id:
            raise RoundAnalysisValidationError(
                "The recording bundle session does not match the analysis session."
            )

        if request.is_pipeline_analysis:
            if self.pipeline_revision_store is None:
                raise RoundAnalysisValidationError("The recording pipeline is not available.")
            revision = self.pipeline_revision_store.get(request.table_observation_revision_id or "")
            if revision is None:
                raise RoundAnalysisValidationError(
                    "The selected table-observation revision is not stored."
                )
            source = revision.manifest.source
            if (
                revision.manifest.content_type != "table_observations"
                or revision.manifest.recording_id != request.recording_id
                or not isinstance(source, RecordingVideoSource)
                or source.video_sha256 != recording.source_sha256
                or not isinstance(revision.content, TableObservationData)
                or not revision.content.observations
            ):
                raise RoundAnalysisValidationError(
                    "The selected table-observation revision is not linked to the recording video."
                )
            for observation in revision.content.observations:
                if observation.session.session_id != expected_session_id:
                    raise RoundAnalysisValidationError(
                        "All table observations must use the analysis session."
                    )
            return ValidatedRoundAnalysisInput(
                request=request,
                packages=(),
                pipeline_revision=revision,
            )

        packages: list[StoredPackage] = []
        for package_id in request.evidence_package_ids:
            package = self.package_store.get(package_id)
            if package is None:
                raise RoundAnalysisValidationError(
                    f"The evidence package {package_id} is not stored."
                )
            if str(package.session_id) != request.session_id:
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

    def recording_catalog(self) -> tuple[RecordingCatalogEntry, ...]:
        """Return canonical recordings with linked packages and prior analyses."""

        packages_by_recording: dict[str, list[StoredPackage]] = {}
        for package in self.package_store.list_metadata():
            if package.state != "stored":
                continue
            try:
                lineage = self._read_lineage(package)
            except RoundAnalysisValidationError:
                continue
            if lineage.parent_recording_id is None or lineage.session_id != str(package.session_id):
                continue
            packages_by_recording.setdefault(lineage.parent_recording_id, []).append(package)

        entries: list[RecordingCatalogEntry] = []
        for recording in self.recording_bundle_store.list_metadata():
            packages = tuple(
                package
                for package in packages_by_recording.get(recording.recording_id, ())
                if str(package.session_id) == recording.session_id
            )
            analyses = self.store.list_by_recording(recording.recording_id)
            try:
                _, _, round_id = self._analysis_identifiers(recording)
                has_pipeline_revision = self._has_selected_pipeline_revision(recording.recording_id)
                blocker = (
                    None
                    if has_pipeline_revision or packages
                    else "No selected table observations or linked evidence packages are available."
                )
            except RoundAnalysisValidationError as error:
                round_id = analyses[0].round_id if analyses else f"round-{recording.recording_id}"
                blocker = str(error)
            entries.append(
                RecordingCatalogEntry(
                    recording=recording,
                    evidence_package_ids=tuple(package.package_id for package in packages),
                    analyses=analyses,
                    round_id=round_id,
                    can_start_analysis=blocker is None,
                    analysis_blocker=blocker,
                )
            )
        return tuple(entries)

    def default_request_for_recording(self, recording_id: str) -> RoundAnalysisCreateRequest:
        """Build a request only when this recording has saved explicit round context."""

        recording = self.recording_bundle_store.get(recording_id)
        if recording is None:
            raise RoundAnalysisValidationError("The recording bundle is not stored.")
        pipeline_revision = self._selected_pipeline_revision(recording_id)
        session_id, game_id, round_id = self._analysis_identifiers(recording)
        context, rules_version = self._saved_round_context(recording_id)
        if context is None or rules_version is None:
            raise RoundAnalysisValidationError(
                "Round context is required before analysis: provide four active players, "
                "dealer, first-trick leader, game ID, round ID, and rules version."
            )
        game_id = context.game_id
        round_id = context.round_id
        search = AnalysisSearchLimits(
            max_missing_plays=1,
            max_hypotheses=256,
            max_search_nodes=250_000,
        )
        if pipeline_revision is not None:
            return RoundAnalysisCreateRequest(
                analysis_id=uuid4(),
                recording_id=recording.recording_id,
                round_id=round_id,
                session_id=session_id,
                table_observation_revision_id=pipeline_revision.manifest.revision_id,
                round_context=context,
                rules_version=rules_version,
                search=search,
            )

        packages = tuple(
            package_id
            for entry in self.recording_catalog()
            if entry.recording.recording_id == recording_id
            for package_id in entry.evidence_package_ids
        )
        if not packages:
            raise RoundAnalysisValidationError(
                "No selected table observations or linked evidence packages are available."
            )
        setup = AnalysisRoundSetup(
            game_id=game_id,
            round_id=round_id,
            ruleset=AnalysisRoundRuleset(name="doko-normal", version="v1"),
            deck_variant="doko-40-v1",
            active_players=context.active_players,
            dealer=context.dealer,
            first_trick_leader=context.first_trick_leader,
        )
        return RoundAnalysisCreateRequest(
            analysis_id=uuid4(),
            recording_id=recording.recording_id,
            round_id=round_id,
            session_id=session_id,
            round_setup=setup,
            evidence_package_ids=list(packages),
            search=search,
        )

    def _saved_round_context(
        self, recording_id: str
    ) -> tuple[AnalysisRoundContext | None, str | None]:
        """Return the newest valid, explicitly saved context for this recording."""

        for analysis in self.store.list_by_recording(recording_id):
            try:
                request = parse_round_analysis_create_request_bytes(
                    analysis.request_json.encode("utf-8")
                )
            except (TypeError, UnicodeError, ValueError):
                continue
            if request.is_pipeline_analysis and request.round_context is not None:
                return request.round_context, request.rules_version
            if request.round_setup is not None:
                setup = request.round_setup
                return (
                    AnalysisRoundContext(
                        game_id=setup.game_id,
                        round_id=setup.round_id,
                        active_players=setup.active_players,
                        dealer=setup.dealer,
                        first_trick_leader=setup.first_trick_leader,
                    ),
                    setup.ruleset.version,
                )
        return None, None

    def _selected_pipeline_revision(self, recording_id: str) -> StoredPipelineRevision | None:
        """Return the selected table-observation revision when it belongs to a recording."""

        revision_id = self._selected_table_observation_revision_id(recording_id)
        if revision_id is None or self.pipeline_revision_store is None:
            return None
        revision = self.pipeline_revision_store.get(revision_id)
        if revision is None or revision.manifest.recording_id != recording_id:
            return None
        if revision.manifest.content_type != "table_observations":
            return None
        return revision

    def _has_selected_pipeline_revision(self, recording_id: str) -> bool:
        """Return whether a selected table-observation revision exists without loading content."""

        revision_id = self._selected_table_observation_revision_id(recording_id)
        if revision_id is None or self.pipeline_revision_store is None:
            return False
        return self.pipeline_revision_store.has_revision(revision_id)

    def _selected_table_observation_revision_id(self, recording_id: str) -> str | None:
        if self.pipeline_selection_store is None:
            return None
        selection = self.pipeline_selection_store.get(recording_id, "table_observations")
        if selection is None:
            return None
        return (
            selection.selected_generated_revision_id
            or selection.selected_completed_reference_revision_id
        )

    def prepare_inputs(self, request: RoundAnalysisCreateRequest) -> None:
        """Resolve and copy pipeline inputs before analysis work is queued."""

        if not request.is_pipeline_analysis:
            return
        selected = self.validate_request(request)
        assert selected.pipeline_revision is not None
        revision = selected.pipeline_revision
        content_bytes = canonical_table_observation_data_bytes(revision.content)
        context = request.round_context
        assert context is not None
        self.artifact_storage.prepare_inputs(
            request.analysis_id,
            {
                "table-observations.json": content_bytes,
                "round-context.json": json.dumps(
                    context.model_dump(mode="json"),
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
                "input-manifest.json": json.dumps(
                    {
                        "table_observation_revision_id": revision.manifest.revision_id,
                        "table_observation_content_sha256": revision.manifest.content_sha256,
                        "rules_version": request.rules_version,
                        "correction_constraint_revision_ids": list(
                            request.correction_constraint_revision_ids
                        ),
                    },
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
            },
        )

    def _analysis_identifiers(self, recording: StoredRecordingBundle) -> tuple[str, str, str]:
        """Read analysis identifiers from one canonical recording source."""

        try:
            session_id = recording.session_id
            source = parse_source_record(
                (
                    self.repository_bundle_storage.bundle_path(recording.recording_id)
                    / "source-record.json"
                ).read_bytes()
            )
        except (OSError, IntakeContractError, TypeError, ValueError) as error:
            raise RoundAnalysisValidationError("The recording metadata is invalid.") from error
        return (
            session_id,
            source.game_id or f"analysis-game-{session_id}",
            source.round_id or f"round-{recording.recording_id}",
        )

    def prepare_job(self, job_id: str, raw_request: dict[str, Any], after_write: Any) -> None:
        """Create the immutable domain record for one accepted job attempt."""
        request = self._request_for_job(job_id, raw_request)
        selected = self.validate_request(request)
        self.store.create(request)
        self.prepare_inputs(request)
        self._write_analysis_lineage(request, selected=selected)
        after_write("round_analysis")

    def _write_analysis_lineage(
        self,
        request: RoundAnalysisCreateRequest,
        *,
        selected: ValidatedRoundAnalysisInput | None = None,
        status: str | None = None,
        analysis: StoredRoundAnalysis | None = None,
        failure: str | None = None,
    ) -> None:
        """Record accepted analysis inputs or its terminal artifact result."""
        writer = self.pipeline_lineage_writer
        if writer is None:
            return
        selected = selected or self.validate_request(request)
        if request.round_context is not None:
            context = request.round_context.model_dump(mode="json", exclude_none=True)
        else:
            setup = request.resolved_round_setup()
            context = {
                "game_id": setup.game_id,
                "round_id": setup.round_id,
                "active_players": list(setup.active_players),
                "dealer": setup.dealer,
                "first_trick_leader": setup.first_trick_leader,
            }
        rules = {
            "name": (
                request.round_setup.ruleset.name
                if request.round_setup is not None
                else "doko-normal"
            ),
            "version": request.rules_version
            or (request.round_setup.ruleset.version if request.round_setup is not None else "v1"),
        }
        packages = [(str(item.package_id), item.manifest_sha256) for item in selected.packages]
        inputs = writer.accept_analysis(
            str(request.analysis_id),
            recording_id=request.recording_id,
            revision_id=(
                None
                if selected.pipeline_revision is None
                else selected.pipeline_revision.manifest.revision_id
            ),
            package_inputs=packages,
            round_context=context,
            rules=rules,
            search_settings=request.search.model_dump(mode="json", exclude_none=True),
        )
        if status is None:
            return
        outputs = []
        if status == "complete" and analysis is not None:
            if (
                analysis.input_artifact_id is None
                or analysis.input_artifact_sha256 is None
                or analysis.result_artifact_id is None
                or analysis.result_artifact_sha256 is None
            ):
                raise RuntimeError("The completed analysis has no exact lineage artifacts.")
            outputs = [
                {
                    "kind": "artifact",
                    "artifact_id": analysis.input_artifact_id,
                    "sha256": analysis.input_artifact_sha256,
                    "role": "analysis_input",
                },
                {
                    "kind": "artifact",
                    "artifact_id": analysis.result_artifact_id,
                    "sha256": analysis.result_artifact_sha256,
                    "role": "analysis_result",
                },
            ]
        writer.finish_analysis(
            str(request.analysis_id),
            status=status,
            inputs=inputs,
            recording_id=request.recording_id,
            round_context=context,
            rules=rules,
            search_settings=request.search.model_dump(mode="json", exclude_none=True),
            outputs=outputs,
            failure=None if failure is None else {"message": failure},
        )

    def verify_job(self, job_id: str, raw_request: dict[str, Any]) -> bool:
        """Verify that accepted inputs are stored under this attempt ID."""
        request = self._request_for_job(job_id, raw_request)
        stored = self.store.get(request.analysis_id)
        if stored is None or stored.request_sha256 != canonical_analysis_request_sha256(request):
            return False
        if request.is_pipeline_analysis:
            path = self.artifact_storage.analysis_path(request.analysis_id) / "inputs"
            return all(
                (path / name).is_file()
                for name in ("table-observations.json", "round-context.json", "input-manifest.json")
            )
        return True

    @staticmethod
    def _request_for_job(job_id: str, raw_request: dict[str, Any]) -> RoundAnalysisCreateRequest:
        request = parse_round_analysis_create_request_bytes(
            json.dumps(
                raw_request,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        del job_id
        return request

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        """Describe the exact selected source artifacts in the Jobs view."""
        parsed = parse_round_analysis_create_request_bytes(
            json.dumps(
                request["request"],
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        selected = self.validate_request(parsed)
        inputs = [
            {"kind": "evidence_package", "id": str(item.package_id), "digest": item.manifest_sha256}
            for item in selected.packages
        ]
        if selected.pipeline_revision is not None:
            inputs.append(
                {
                    "kind": "pipeline_revision",
                    "id": selected.pipeline_revision.manifest.revision_id,
                    "digest": selected.pipeline_revision.manifest.content_sha256,
                }
            )
        return {
            "label": "Analyze round",
            "inputs": inputs,
            "implementation": {
                "round_setup": parsed.resolved_round_setup().model_dump(mode="json"),
                "search": parsed.search.model_dump(mode="json"),
                "correction_constraint_revision_ids": list(
                    parsed.correction_constraint_revision_ids
                ),
            },
        }

    def verify_job_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        request = parse_round_analysis_create_request_bytes(
            json.dumps(
                job.request,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        analysis = self.store.get(request.analysis_id)
        return bool(
            analysis is not None
            and analysis.state == "complete"
            and len(results) == 1
            and results[0].get("kind") == "round_analysis"
            and results[0].get("id") == str(request.analysis_id)
            and results[0].get("digest") == analysis.result_artifact_sha256
        )

    def reconcile_jobs(self, jobs: list[Job]) -> None:
        """Keep interrupted analysis records aligned with Job Manager recovery."""
        for job in jobs:
            if job.type != "round_analysis" or job.state not in {"interrupted", "cancelled"}:
                continue
            request = parse_round_analysis_create_request_bytes(
                json.dumps(
                    job.request,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            )
            analysis = self.store.get(request.analysis_id)
            if analysis is not None and analysis.state not in {"complete", "failed"}:
                try:
                    failed = self.store.mark_failed(request.analysis_id, ANALYSIS_WORKER_FAILURE)
                    self._write_analysis_lineage(
                        request,
                        status="failed",
                        analysis=failed,
                        failure=ANALYSIS_WORKER_FAILURE,
                    )
                except (RoundAnalysisNotFound, ValueError):
                    continue

    def execute_job(self, job: Job, token: Any, manager: JobManager) -> None:
        """Analyze packages and reconstruct one round as a managed job."""
        request_from_job = parse_round_analysis_create_request_bytes(
            json.dumps(
                job.request,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        analysis_id = request_from_job.analysis_id
        analysis = self.store.get(analysis_id)
        if analysis is None or analysis.state in {"complete", "failed"}:
            return
        request_id = job.correlation_id or job.id
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
            selected = self.validate_request(request)
            previous = analysis
            analysis = self.store.update_progress(
                analysis_id, state="analyzing_evidence", completed=0
            )
            _log_state_change(previous, analysis, request_id)
            observations: list[StoredTableObservation | TableObservation] = []
            if selected.request.is_pipeline_analysis:
                observations.extend(self._read_prepared_pipeline_observations(analysis_id))
            total = len(selected.packages)
            manager.report_progress(
                job.id,
                phase="Analyze evidence",
                completed=0,
                total=total,
                unit="packages",
                step_id="analysis",
            )
            for index, package in enumerate(selected.packages, start=1):
                token.check()
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "round_analysis_package_started",
                    **_analysis_context(analysis, request_id),
                    package_id=str(package.package_id),
                    package_index=index,
                    total_packages=total,
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
                    total_packages=total,
                    analyzer=observation.analyzer_name,
                    analyzer_version=observation.analyzer_version,
                    analysis_status=observation.status,
                )
                analysis = self.store.update_progress(
                    analysis_id, state="analyzing_evidence", completed=index
                )
                manager.report_progress(
                    job.id,
                    phase="Analyze evidence",
                    completed=index,
                    total=total,
                    unit="packages",
                    step_id="analysis",
                )
            token.check()
            previous = analysis
            analysis = self.store.update_progress(
                analysis_id, state="reconstructing", completed=total
            )
            _log_state_change(previous, analysis, request_id)
            manager.report_progress(
                job.id,
                phase="Reconstruct round",
                completed=0,
                total=1,
                unit="rounds",
                step_id="reconstruction",
            )
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
            token.check()
            expected_digest = hashlib.sha256(artifacts[1]).hexdigest()
            output = {
                "kind": "round_analysis",
                "id": str(analysis_id),
                "digest": expected_digest,
                "available": True,
            }

            def commit() -> None:
                published = self.artifact_storage.publish(analysis_id, artifacts[0], artifacts[1])
                completed = self.store.mark_complete(
                    analysis_id,
                    result_status=result.status,
                    result_json=artifacts[1].decode("utf-8"),
                    input_artifact_id=published.input.relative_path,
                    input_artifact_sha256=published.input.sha256,
                    result_artifact_id=published.result.relative_path,
                    result_artifact_sha256=published.result.sha256,
                )
                self._write_analysis_lineage(request, status="complete", analysis=completed)
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
                log_event(
                    LOGGER,
                    logging.INFO,
                    "round_analysis_completed",
                    **_analysis_fields(completed, request_id),
                    state="complete",
                    result_status=result.status,
                )

            if not manager.publish(job.id, [output], commit):
                raise JobCancelled("job cancellation requested before analysis publication")
            manager.report_progress(
                job.id,
                phase="Reconstruct round",
                completed=1,
                total=1,
                unit="rounds",
                step_id="reconstruction",
            )
        except JobCancelled:
            self._fail_analysis(str(analysis_id))
            raise
        except Exception as error:
            LOGGER.exception("round_analysis_job_failed", extra={"job_id": job.id})
            self._fail_analysis(str(analysis_id))
            failed = self.store.get(analysis_id)
            if failed is not None:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "round_analysis_failed",
                    exc_info=_exception_info(error),
                    **_analysis_fields(failed, request_id),
                    state="failed",
                    error=failed.error,
                )
            raise RuntimeError(ANALYSIS_WORKER_FAILURE) from None

    def _fail_analysis(self, analysis_id: str) -> None:
        analysis = self.store.get(analysis_id)
        if analysis is not None and analysis.state not in {"complete", "failed"}:
            analysis = self.store.mark_failed(analysis_id, ANALYSIS_WORKER_FAILURE)
            try:
                request = parse_round_analysis_create_request_bytes(
                    analysis.request_json.encode("utf-8")
                )
                self._write_analysis_lineage(
                    request,
                    status="failed",
                    analysis=analysis,
                    failure=ANALYSIS_WORKER_FAILURE,
                )
            except (TypeError, UnicodeError, ValueError, RoundAnalysisValidationError):
                LOGGER.exception("round_analysis_lineage_failure")

    def _run_reconstruction(
        self,
        selected: ValidatedRoundAnalysisInput,
        observations: list[StoredTableObservation | TableObservation],
    ) -> tuple[RoundReconstructionRunResult, tuple[bytes, bytes]]:
        request = selected.request
        self.artifact_storage.operations_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{request.analysis_id}-", dir=self.artifact_storage.operations_root
        ) as scratch_root:
            if request.is_pipeline_analysis:
                observation_paths: list[str] = []
                source_paths = []
                for index, observation in enumerate(observations):
                    assert isinstance(observation, TableObservation)
                    relative_path = (
                        f"pipeline-observations/{index:04d}-{observation.observation_id}.json"
                    )
                    path = Path(scratch_root) / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(
                        canonical_json_bytes(observation.model_dump(mode="json", exclude_none=True))
                    )
                    observation_paths.append(relative_path)
                    source_paths.append(path)
            else:
                observation_paths = [observation.relative_path for observation in observations]
                source_paths = [
                    self.evidence_storage.root / relative_path
                    for relative_path in observation_paths
                ]
            reconstruction_request = RoundReconstructionRunRequest(
                run_id=str(request.analysis_id),
                round_setup=request.resolved_round_setup().to_shared(),
                observation_paths=tuple(observation_paths),
                search=request.search.to_shared(),
                output_root=".",
            )
            artifacts = run_round_reconstruction_values(
                reconstruction_request,
                source_paths,
                scratch_root,
            )
            return (
                artifacts.result,
                (artifacts.input_path.read_bytes(), artifacts.result_path.read_bytes()),
            )

    def _read_prepared_pipeline_observations(self, analysis_id: UUID) -> list[TableObservation]:
        """Read the immutable observation copy prepared before queueing."""

        path = (
            self.artifact_storage.analysis_path(analysis_id) / "inputs" / "table-observations.json"
        )
        try:
            raw = path.read_bytes()
            data = parse_table_observation_data_bytes(raw)
            if canonical_table_observation_data_bytes(data) != raw:
                raise ValueError("the prepared table observations are not canonical")
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise RoundAnalysisValidationError(
                "The prepared table-observation input is unavailable or invalid."
            ) from error
        return list(data.observations)

    def status(self, analysis_id: UUID) -> RoundAnalysisStatus:
        """Convert one durable row to the public status document."""

        analysis = self.store.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        result = self._result_from_analysis(analysis)
        return RoundAnalysisStatus(
            analysis_id=analysis.analysis_id,
            recording_id=analysis.recording_id,
            round_id=analysis.round_id,
            session_id=analysis.session_id,
            round_context=self._context_from_analysis(analysis),
            rules_version=self._rules_version_from_analysis(analysis),
            state=analysis.state,  # type: ignore[arg-type]
            total_evidence_packages=analysis.total_evidence_packages,
            completed_evidence_packages=analysis.completed_evidence_packages,
            result=result,
            error=analysis.error,
            created_at=analysis.created_at,
            started_at=analysis.started_at,
            completed_at=analysis.completed_at,
        )

    @staticmethod
    def _context_from_analysis(analysis: StoredRoundAnalysis) -> AnalysisRoundContext | None:
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
        except (TypeError, UnicodeError, ValueError):
            return None
        if request.round_context is not None:
            return request.round_context
        if request.round_setup is None:
            return None
        setup = request.round_setup
        return AnalysisRoundContext(
            game_id=setup.game_id,
            round_id=setup.round_id,
            active_players=setup.active_players,
            dealer=setup.dealer,
            first_trick_leader=setup.first_trick_leader,
        )

    @staticmethod
    def _rules_version_from_analysis(analysis: StoredRoundAnalysis) -> str | None:
        try:
            request = parse_round_analysis_create_request_bytes(
                analysis.request_json.encode("utf-8")
            )
        except (TypeError, UnicodeError, ValueError):
            return None
        if request.rules_version is not None:
            return request.rules_version
        if request.round_setup is not None:
            return request.round_setup.ruleset.version
        return None

    def timeline(self, analysis_id: UUID) -> RoundAnalysisTimeline:
        """Return the verified immutable timeline for one completed analysis."""

        analysis = self.store.get(analysis_id)
        if analysis is None:
            raise RoundAnalysisNotFound("The round analysis was not found.")
        return self.timeline_projector.project(analysis)

    def frame(self, analysis_id: UUID, package_id: UUID, part_name: str) -> TimelineFrameFile:
        """Return one verified frame owned by one completed analysis."""

        analysis = self.store.get(analysis_id)
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
        analysis = self.store.get(analysis_id)
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


def _exception_info(
    error: BaseException,
) -> tuple[type[BaseException], BaseException, object] | None:
    """Return traceback information for one failed analysis operation."""
    if error.__traceback__ is None:
        return None
    return type(error), error, error.__traceback__


__all__ = [
    "ANALYSIS_WORKER_FAILURE",
    "RoundAnalysisService",
    "RoundAnalysisValidationError",
    "ValidatedRoundAnalysisInput",
]
