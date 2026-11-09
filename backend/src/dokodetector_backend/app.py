"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from dokodetector_backend.api import router
from dokodetector_backend.automated_pipeline_jobs import AutomatedPipelineJobParticipant
from dokodetector_backend.automated_pipeline_run import (
    AutomatedPipelineRunService,
    AutomatedPipelineRunStore,
)
from dokodetector_backend.calculation_jobs import CalculationJobs
from dokodetector_backend.config import Settings
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.event_jobs import EventJobParticipant
from dokodetector_backend.event_pipeline_service import EventProcessorProvider
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.evidence_package_store import EvidencePackageStore
from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.frame_review_api import router as frame_review_router
from dokodetector_backend.frame_review_workflow_store import FrameReviewWorkflowStore
from dokodetector_backend.gemini_analyzer import (
    create_configured_processor_registries,
    create_lazy_configured_analyzer,
    validate_configured_processor_settings,
)
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.jobs_api import JobManagerService, JobTypeRegistry
from dokodetector_backend.jobs_api import router as jobs_router
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.observation_jobs import ObservationJobParticipant
from dokodetector_backend.pending_video_api import router as pending_video_router
from dokodetector_backend.pending_video_storage import PendingVideoStorage
from dokodetector_backend.persistence import EvidencePackagePersister
from dokodetector_backend.pipeline_api import router as pipeline_router
from dokodetector_backend.pipeline_composition import (
    build_pipeline_composition,
    install_pipeline_composition,
)
from dokodetector_backend.pipeline_run_preflight import validate_local_stage_providers
from dokodetector_backend.proposed_card_scene_jobs import ProposedCardSceneJobParticipant
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.recording_history_store import RecordingHistoryStore
from dokodetector_backend.recording_state_api import router as recording_state_router
from dokodetector_backend.recording_state_store import RecordingStateSnapshotStore
from dokodetector_backend.recording_state_working_editor import RecordingStateWorkingEditor
from dokodetector_backend.recording_thumbnail import RecordingThumbnailCache
from dokodetector_backend.recordings_api import router as recordings_router
from dokodetector_backend.repository_bundle_api import router as repository_bundle_router
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_api import router as round_analysis_router
from dokodetector_backend.round_analysis_jobs import RoundAnalysisJobParticipant
from dokodetector_backend.round_analysis_service import RoundAnalysisService
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.round_analysis_store import RoundAnalysisStore
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.table_observation_store import TableObservationStore
from dokodetector_backend.visible_card_jobs import VisibleCardJobParticipant
from dokodetector_backend.visual_identity_jobs import VisualIdentityJobParticipant

if TYPE_CHECKING:
    from table_evidence_analyzer import TableEvidenceAnalyzer


LOGGER = logging.getLogger(__name__)


def _recording_session_id(recording_store: RecordingBundleStore):
    """Return the stored session identity for one accepted recording."""

    def resolve(recording_id: str) -> str:
        recording = recording_store.get(recording_id)
        if recording is None:
            raise ValueError(f"The recording bundle was not found: {recording_id}.")
        return recording.session_id

    return resolve


def create_app(
    settings: Settings | None = None,
    *,
    run_round_analysis_synchronously: bool = False,
    analyzer: TableEvidenceAnalyzer | None = None,
    visible_card_provider: Any | None = None,
    visible_card_frame_resolver: Any | None = None,
    visible_card_identity_classifier: Any | None = None,
    event_provider: EventProcessorProvider | None = None,
) -> FastAPI:
    """Create the local backend application."""

    app_settings = settings or Settings()
    lifecycle_services: tuple[Any, ...] = ()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        for service in lifecycle_services:
            await service.start()
        log_event(
            LOGGER,
            logging.INFO,
            "backend_started",
            host=app_settings.server_host,
            port=app_settings.server_port,
        )
        try:
            yield
        finally:
            for service in reversed(lifecycle_services):
                await service.stop()

    app = FastAPI(title="DokoDetector Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.job_type_registry = JobTypeRegistry(app_settings.operations_root)
    app.state.job_manager_service = JobManagerService(
        app_settings.operations_root,
        app.state.job_type_registry,
    )
    app.state.storage = EvidenceStorage(app_settings.evidence_root)
    app.state.operations_storage = EvidenceStorage(app_settings.operations_root)
    app.state.recording_state_store = RecordingStateSnapshotStore(app_settings.operations_root)
    app.state.recording_history_store = RecordingHistoryStore(app_settings.operations_root)
    app.state.round_analysis_storage = RoundAnalysisArtifactStorage(app_settings.operations_root)
    app.state.round_analysis_store = RoundAnalysisStore(app.state.round_analysis_storage)
    app.state.evidence_package_storage = EvidencePackageStorage(
        app_settings.evidence_package_intake_root
    )
    app.state.evidence_package_store = EvidencePackageStore(app.state.evidence_package_storage)
    app.state.table_observation_store = TableObservationStore(app.state.operations_storage)
    app.state.persister = EvidencePackagePersister(
        app.state.evidence_package_store,
    )
    app.state.repository_bundle_storage = RepositoryBundleStorage(
        app_settings.repository_intake_root
    )
    app.state.recording_bundle_store = RecordingBundleStore(app.state.repository_bundle_storage)
    app.state.recording_thumbnail_cache = RecordingThumbnailCache(
        app_settings.evidence_root / "recording-thumbnails"
    )
    app.state.frame_review_workflow_store = FrameReviewWorkflowStore(
        app_settings.operations_root / "frame-review-queues"
    )
    app.state.pending_video_storage = PendingVideoStorage(app_settings.pending_video_root)
    app.state.readiness_state = "unknown"
    if analyzer is None:
        validate_configured_processor_settings(app_settings)
    visible_card_providers, visible_card_identity_classifiers = (
        create_configured_processor_registries(app_settings)
    )
    app.state.visible_card_providers = visible_card_providers
    app.state.analyzer = analyzer or create_lazy_configured_analyzer(
        app_settings,
        visible_card_providers,
        visible_card_identity_classifiers,
    )
    app.state.visible_card_provider = (
        visible_card_provider
        if visible_card_provider is not None
        else getattr(analyzer, "provider", None)
        if analyzer is not None
        else None
    )
    app.state.visible_card_identity_classifier = (
        visible_card_identity_classifier
        if visible_card_identity_classifier is not None
        else getattr(analyzer, "classifier", None)
        if analyzer is not None
        else None
    )
    if visible_card_provider is not None:
        visible_card_providers.register("cloud", visible_card_provider)
        visible_card_providers.register("local", visible_card_provider)
        provider_name = getattr(visible_card_provider, "name", None)
        if isinstance(provider_name, str) and provider_name:
            visible_card_providers.register(provider_name, visible_card_provider)
    elif analyzer is not None and app_settings.visible_card_provider != "gemini":
        visible_card_providers.register("local", app.state.visible_card_provider)
        visible_card_providers.register(
            app_settings.visible_card_provider, app.state.visible_card_provider
        )
    elif analyzer is not None:
        visible_card_providers.register("cloud", app.state.visible_card_provider)
        visible_card_providers.register("gemini", app.state.visible_card_provider)
    if visible_card_identity_classifier is not None:
        visible_card_identity_classifiers.register("cloud", visible_card_identity_classifier)
        visible_card_identity_classifiers.register("local", visible_card_identity_classifier)
        classifier_name = getattr(visible_card_identity_classifier, "name", None)
        if isinstance(classifier_name, str) and classifier_name:
            visible_card_identity_classifiers.register(
                classifier_name, visible_card_identity_classifier
            )
    elif analyzer is not None and app_settings.visible_card_identity_classifier == "local":
        visible_card_identity_classifiers.register(
            "local", app.state.visible_card_identity_classifier
        )
    elif analyzer is not None:
        visible_card_identity_classifiers.register(
            "cloud", app.state.visible_card_identity_classifier
        )
        visible_card_identity_classifiers.register(
            "gemini", app.state.visible_card_identity_classifier
        )
    pipeline_composition = build_pipeline_composition(
        app_settings,
        app.state.recording_bundle_store,
        app.state.repository_bundle_storage,
        app.state.round_analysis_store,
        visible_card_provider=app.state.visible_card_provider,
        visible_card_providers=visible_card_providers,
        visible_card_frame_resolver=visible_card_frame_resolver,
        visible_card_identity_classifier=app.state.visible_card_identity_classifier,
        visible_card_identity_classifiers=visible_card_identity_classifiers,
        event_provider=event_provider,
    )
    install_pipeline_composition(app.state, pipeline_composition)
    app.state.recording_state_working_editor = RecordingStateWorkingEditor(
        app.state.recording_state_store,
        app.state.pipeline_node_edits,
    )
    app.state.proposed_card_scene_pipeline_service.job_manager_provider = (
        app.state.job_manager_service.get_manager
    )
    app.state.visual_identity_pipeline_service.job_manager_provider = (
        app.state.job_manager_service.get_manager
    )
    app.state.observation_pipeline_service.job_manager_provider = (
        app.state.job_manager_service.get_manager
    )
    app.state.round_analysis_service = RoundAnalysisService(
        app.state.round_analysis_store,
        app.state.evidence_package_store,
        app.state.table_observation_store,
        app.state.round_analysis_storage,
        app.state.recording_bundle_store,
        app.state.repository_bundle_storage,
        app.state.analyzer,
        pipeline_selection_store=app.state.pipeline_selection_store,
        pipeline_lineage_writer=app.state.pipeline_lineage_writer,
    )
    calculation_jobs = CalculationJobs(
        app_settings.operations_root,
        app.state.calibration_refinement_service,
        app.state.round_analysis_service,
    )
    app.state.calculation_jobs = calculation_jobs
    for calculation_type in ("calibration_preview", "counterfactual"):
        app.state.job_type_registry.register(
            calculation_type,
            lambda _request: None,
            calculation_jobs,
            lambda job, claims, token: calculation_jobs.handle(
                job, claims, token, app.state.job_manager_service.get_manager()
            ),
            Claims(cpu=1),
        )
    event_job_participant = EventJobParticipant(app.state.event_pipeline_service)
    for event_job_type in ("event_processing", "event_import"):
        app.state.job_type_registry.register(
            event_job_type,
            lambda _request: None,
            event_job_participant,
            lambda job, claims, token, participant=event_job_participant: participant.handle(
                job,
                claims,
                token,
                app.state.job_manager_service.get_manager(),
            ),
            Claims(cpu=1, locks=()),
        )
    visible_card_job_participant = VisibleCardJobParticipant(
        app.state.visible_card_pipeline_service
    )
    app.state.job_type_registry.register(
        "visible_card_detection",
        lambda _request: None,
        visible_card_job_participant,
        lambda job, claims, token, participant=visible_card_job_participant: participant.handle(
            job,
            claims,
            token,
            app.state.job_manager_service.get_manager(),
        ),
        Claims(cpu=1, locks=()),
    )
    proposed_card_scene_job_participant = ProposedCardSceneJobParticipant(
        app.state.proposed_card_scene_pipeline_service
    )
    app.state.job_type_registry.register(
        "proposed_card_scene_creation",
        lambda _request: None,
        proposed_card_scene_job_participant,
        lambda job, claims, token, participant=proposed_card_scene_job_participant: (
            participant.handle(
                job,
                claims,
                token,
                app.state.job_manager_service.get_manager(),
            )
        ),
        Claims(cpu=1, locks=()),
    )
    visual_identity_job_participant = VisualIdentityJobParticipant(
        app.state.visual_identity_pipeline_service
    )
    app.state.job_type_registry.register(
        "visual_identity_classification",
        lambda _request: None,
        visual_identity_job_participant,
        lambda job, claims, token, participant=visual_identity_job_participant: participant.execute(
            job,
            claims,
            token,
            app.state.job_manager_service.get_manager(),
        ),
        Claims(cpu=1, locks=()),
    )
    observation_job_participant = ObservationJobParticipant(app.state.observation_pipeline_service)
    app.state.job_type_registry.register(
        "table_observation_assembly",
        lambda _request: None,
        observation_job_participant,
        lambda job, claims, token, participant=observation_job_participant: participant.handle(
            job,
            claims,
            token,
            app.state.job_manager_service.get_manager(),
        ),
        Claims(cpu=1, locks=()),
    )
    round_analysis_job_participant = RoundAnalysisJobParticipant(app.state.round_analysis_service)
    app.state.job_type_registry.register(
        "round_analysis",
        lambda _request: None,
        round_analysis_job_participant,
        lambda job, claims, token, participant=round_analysis_job_participant: participant.handle(
            job,
            claims,
            token,
            app.state.job_manager_service.get_manager(),
        ),
        Claims(cpu=1, locks=()),
    )
    recovered_event_count = app.state.event_pipeline_service.recover_interrupted_runs()
    log_event(
        LOGGER,
        logging.DEBUG,
        "event_pipeline_recovery_checked",
        failed_count=recovered_event_count,
    )
    app.state.run_round_analysis_synchronously = run_round_analysis_synchronously
    app.state.automated_pipeline_run_service = AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(app_settings.pipeline_root / "automated-runs"),
        recording_source_provider=app.state.event_pipeline_service.get_recording_source,
        recording_provider_validator=lambda recording_id, stage_requests: (
            validate_local_stage_providers(
                recording_id,
                stage_requests,
                event_service=app.state.event_pipeline_service,
                visible_card_service=app.state.visible_card_pipeline_service,
                visual_identity_service=app.state.visual_identity_pipeline_service,
            )
        ),
        round_session_provider=_recording_session_id(app.state.recording_bundle_store),
    )
    automated_pipeline_job_participant = AutomatedPipelineJobParticipant(
        app.state.automated_pipeline_run_service,
        app.state,
    )
    app.state.job_type_registry.register(
        "automated_pipeline",
        lambda _request: None,
        automated_pipeline_job_participant,
        lambda job, claims, token, participant=automated_pipeline_job_participant: (
            participant.handle(
                job,
                claims,
                token,
                app.state.job_manager_service.get_manager(),
            )
        ),
        Claims(cpu=1, locks=()),
    )
    lifecycle_services = (
        app.state.job_manager_service,
        *pipeline_composition.lifecycle_services,
    )
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(jobs_router)
    app.include_router(repository_bundle_router)
    app.include_router(pending_video_router)
    app.include_router(round_analysis_router)
    app.include_router(recordings_router)
    app.include_router(recording_state_router)
    app.include_router(pipeline_router)
    app.include_router(frame_review_router)
    _mount_frontend(app, app_settings.frontend_dist)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the process is running."""

        return {"status": "ok"}

    @app.get("/health/ready", response_model=None)
    def readiness(request: Request) -> dict[str, str] | JSONResponse:
        """Check the required filesystem roots and atomic replacement support."""

        request_id = get_or_create_request_id(request)
        try:
            _check_evidence_directory(app.state.operations_storage.table_observations_root)
            _check_evidence_directory(app.state.round_analysis_storage.root)
            _check_evidence_directory(app.state.evidence_package_storage.root)
            _check_evidence_directory(app.state.repository_bundle_storage.root)
            _check_evidence_directory(app.state.pending_video_storage.root)
            _check_evidence_directory(app.state.event_pipeline_service.storage.pipeline_root)
            _check_evidence_directory(app.state.automated_pipeline_run_service.store.root)
            _check_atomic_runtime_probe(app.state.storage.root)
        except OSError:
            log_event(
                LOGGER,
                logging.DEBUG,
                "backend_readiness_checked",
                request_id=request_id,
                result="not_ready",
            )
            if app.state.readiness_state != "not_ready":
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "backend_not_ready",
                    request_id=request_id,
                    reason="local_dependency_unavailable",
                )
            app.state.readiness_state = "not_ready"
            return JSONResponse(status_code=503, content={"status": "not_ready"})

        log_event(
            LOGGER,
            logging.DEBUG,
            "backend_readiness_checked",
            request_id=request_id,
            result="ready",
        )
        if app.state.readiness_state != "ready":
            log_event(LOGGER, logging.INFO, "backend_ready", request_id=request_id)
        app.state.readiness_state = "ready"
        return {"status": "ok"}

    return app


def _mount_frontend(app: FastAPI, frontend_dist: Path) -> None:
    """Serve the built browser application when its package is present."""

    entrypoint = frontend_dist / "index.html"
    assets = frontend_dist / "assets"
    if not entrypoint.is_file() or not assets.is_dir():
        return

    app.mount(
        "/round-analyses/assets",
        StaticFiles(directory=assets),
        name="frontend-assets",
    )
    app.mount(
        "/assets",
        StaticFiles(directory=assets),
        name="frontend-assets-root",
    )

    @app.get("/", include_in_schema=False)
    def frontend_root() -> FileResponse:
        """Return the SPA entry document for the recording catalog."""

        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/recordings/{recording_id}", include_in_schema=False)
    def frontend_recording(recording_id: str) -> FileResponse:
        """Return the SPA entry document for a direct recording load or refresh."""

        del recording_id
        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/recordings/{recording_id}/pipeline", include_in_schema=False)
    def frontend_recording_pipeline(recording_id: str) -> FileResponse:
        """Return the SPA entry document for a direct pipeline load or refresh."""

        del recording_id
        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/recordings/{recording_id}/pipeline/{stage:path}", include_in_schema=False)
    def frontend_recording_pipeline_stage(recording_id: str, stage: str) -> FileResponse:
        """Return the SPA entry document for a pipeline stage or comparison refresh."""

        del recording_id, stage
        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/round-analyses/", include_in_schema=False)
    def frontend_catalog() -> FileResponse:
        """Return the SPA entry document for the recording catalog."""

        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/round-analyses/{analysis_id}", include_in_schema=False)
    def frontend_entrypoint(analysis_id: str) -> FileResponse:
        """Return the SPA entry document for a direct analysis load or refresh."""

        del analysis_id
        return FileResponse(
            entrypoint,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )


def _check_evidence_directory(directory: os.PathLike[str] | str) -> None:
    """Verify that one required filesystem root supports local reads and writes."""

    evidence_directory = os.fspath(directory)
    os.makedirs(evidence_directory, exist_ok=True)
    if not os.path.isdir(evidence_directory) or not os.access(
        evidence_directory, os.R_OK | os.X_OK | os.W_OK
    ):
        raise OSError("The evidence directory is not accessible.")

    with tempfile.NamedTemporaryFile(
        mode="w+b", prefix=".readiness-", dir=evidence_directory
    ) as probe:
        probe.write(b"ready")
        probe.flush()
        probe.seek(0)
        if probe.read() != b"ready":
            raise OSError("The evidence directory failed its write check.")


def _check_atomic_runtime_probe(directory: os.PathLike[str] | str) -> None:
    """Verify a safe JSON write-and-replace in the mutable runtime root."""

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    probe_directory = Path(tempfile.mkdtemp(prefix=".readiness-", dir=root))
    probe_path = probe_directory / "probe.json"
    try:
        atomic_replace_json(probe_path, {"status": "ready"})
        if json.loads(probe_path.read_text(encoding="utf-8")) != {"status": "ready"}:
            raise OSError("The runtime root failed its atomic replacement check.")
    finally:
        shutil.rmtree(probe_directory, ignore_errors=True)
