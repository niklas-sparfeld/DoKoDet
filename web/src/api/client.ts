import type { components } from "./openapi";
import type {
  CalibrationRefinementApplyResponse,
  CalibrationRefinementResponse,
  PipelineCalibration,
} from "./calibrationContracts";
import type {
  RoundAnalysisCreateRequest,
  RoundAnalysisStatus,
  RoundAnalysisTimeline,
  RoundCounterfactualResponse,
} from "./analysisContracts";
import type {
  AutomatedPipelineRun,
  AutomatedPipelineStartRequest,
  FrameReviewPageResponse,
  FrameReviewWorkflowResponse,
  PipelineComparisonRequest,
  PipelineComparisonResponse,
  PipelineEventResult,
  PipelineProposalResultResponse,
  PipelineProposalRunResponse,
  PipelineRunResponse,
  PipelineRunStartRequest,
  PipelineSelectableContentType,
  PipelineSelectionResponse,
  PipelineSelectionUpdateRequest,
  PipelineStageKey,
  PipelineVisibleCardResult,
  PipelineVisualIdentityResult,
  PipelineWorkspace,
} from "./pipelineContracts";
import type {
  RecordingDetail,
  RecordingListResponse,
} from "./recordingContracts";
import {
  ApiError,
  jsonHeaders,
  readResponseBody,
  requestJson,
} from "./transport";
import type {
  EnqueueJobBody,
  JobDetail,
  JobListResponse,
  JobLogPage,
} from "./jobsContracts";

export { ApiError } from "./transport";
export type * from "./recordingContracts";
export type * from "./pipelineContracts";
export type * from "./calibrationContracts";
export type * from "./analysisContracts";
export type {
  AutomatedPipelineRun,
  AutomatedPipelineStartRequest,
  PipelineWorkspaceStage,
  PipelineRun,
  PipelineCompatibleInputSet,
  PipelineWorkspaceProcessorInputReference,
  PipelineSelection,
} from "./pipelineContracts";
export type {
  EnqueueJobBody,
  JobDetail,
  JobListResponse,
  JobLogPage,
} from "./jobsContracts";

export interface DokoDetectorClient {
  listJobs(options?: {
    scope?: "active" | "history" | "all";
    cursor?: string;
    limit?: number;
    signal?: AbortSignal;
  }): Promise<JobListResponse>;
  getJobLogs(
    jobId: string,
    options?: { after?: number; limit?: number; signal?: AbortSignal },
  ): Promise<JobLogPage>;
  cancelJob(jobId: string, init?: RequestInit): Promise<JobDetail>;
  enqueueJob(
    payload: EnqueueJobBody,
    idempotencyKey: string,
    init?: RequestInit,
  ): Promise<JobDetail>;
  getJob(jobId: string, init?: RequestInit): Promise<JobDetail>;
  getCalibrationPreview(
    jobId: string,
    init?: RequestInit,
  ): Promise<CalibrationRefinementResponse>;
  retryJob(
    jobId: string,
    idempotencyKey: string,
    init?: RequestInit,
  ): Promise<JobDetail>;
  moveJob(
    groupId: string,
    beforeGroupId: string | null,
    expectedRevision: number,
  ): Promise<components["schemas"]["QueueMoveResponse"]>;
  startAutomatedPipelineRun(
    recordingId: string,
    payload: AutomatedPipelineStartRequest,
    init?: RequestInit,
  ): Promise<AutomatedPipelineRun>;
  getAutomatedPipelineRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<AutomatedPipelineRun>;
  getFrameReviewPage(options?: {
    cursor?: number;
    limit?: number;
    state?: string;
    signal?: AbortSignal;
  }): Promise<FrameReviewPageResponse>;
  updateFrameReviewWorkflow(
    recordingId: string,
    itemId: string,
    payload: {
      queue_digest: string;
      action: "defer" | "resume" | "set_resume" | "save_review";
      node_id?: string;
      revision_id?: string;
      review_id?: string;
    },
    init?: RequestInit,
  ): Promise<FrameReviewWorkflowResponse>;
  listRecordings(init?: RequestInit): Promise<RecordingListResponse>;
  getRecording(
    recordingId: string,
    init?: RequestInit,
  ): Promise<RecordingDetail>;
  getRecordingPipeline(
    recordingId: string,
    init?: RequestInit,
    stageKey?: PipelineStageKey | null,
  ): Promise<PipelineWorkspace>;
  updatePipelineSelection(
    recordingId: string,
    contentType: PipelineSelectableContentType,
    payload: PipelineSelectionUpdateRequest,
    init?: RequestInit,
  ): Promise<PipelineSelectionResponse>;
  comparePipelineRuns(
    recordingId: string,
    payload: PipelineComparisonRequest,
    init?: RequestInit,
  ): Promise<PipelineComparisonResponse>;
  startVisibleCardRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  startProposedCardSceneRun(
    recordingId: string,
    payload: {
      run_id: string;
      input_node_ref: {
        node_id: string;
        revision_id: string;
        revision_policy: "current_head" | "historical";
      };
    },
    init?: RequestInit,
  ): Promise<PipelineProposalRunResponse>;
  listProposedCardSceneRuns(
    recordingId: string,
    init?: RequestInit,
  ): Promise<{ recording_id: string; runs: PipelineProposalRunResponse[] }>;
  getProposedCardSceneResult(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineProposalResultResponse>;
  startCalibrationRefinement(
    recordingId: string,
    payload: { proposal_revision_id: string; draft_id?: string },
    init?: RequestInit,
  ): Promise<CalibrationRefinementResponse>;
  getCalibrationRefinement(
    recordingId: string,
    proposalRevisionId: string,
    draftId?: string,
    init?: RequestInit,
  ): Promise<CalibrationRefinementResponse>;
  getPipelineCalibration(
    recordingId: string,
    calibrationRevisionId: string,
    init?: RequestInit,
  ): Promise<PipelineCalibration>;
  updateCalibrationRefinement(
    recordingId: string,
    proposalRevisionId: string,
    payload: {
      draft_id: string;
      expected_revision: number;
      command: Record<string, unknown>;
    },
    init?: RequestInit,
  ): Promise<CalibrationRefinementResponse>;
  discardCalibrationRefinement(
    recordingId: string,
    payload: { proposal_revision_id: string; draft_id: string },
    init?: RequestInit,
  ): Promise<CalibrationRefinementResponse>;
  applyCalibrationRefinement(
    recordingId: string,
    proposalRevisionId: string,
    payload: {
      draft_id: string;
      expected_revision: number;
      preview_digest: string;
      operator_id: string;
      confirm_affected?: boolean;
    },
    init?: RequestInit,
  ): Promise<CalibrationRefinementApplyResponse>;
  startVisualIdentityRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  listVisualIdentityProposedCropInputs(
    recordingId: string,
    init?: RequestInit,
  ): Promise<{
    recording_id: string;
    inputs: Array<{
      node_id: string;
      revision_id: string;
      created_at: string;
      proposal_data_digest: string;
      detector_revision_id: string;
      calibration_revision_id: string;
      supported_frame_count: number;
      unsupported_frame_count: number;
    }>;
  }>;
  startObservationRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  getEventResult(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineEventResult>;
  getVisibleCardResult(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineVisibleCardResult>;
  getVisualIdentityResult(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineVisualIdentityResult>;
  startRecordingAnalysis(
    recordingId: string,
    init?: RequestInit,
  ): Promise<RoundAnalysisStatus>;
  createRoundAnalysis(
    payload: RoundAnalysisCreateRequest,
    init?: RequestInit,
  ): Promise<RoundAnalysisStatus>;
  getRoundAnalysisStatus(
    analysisId: string,
    init?: RequestInit,
  ): Promise<RoundAnalysisStatus>;
  getRoundAnalysisTimeline(
    analysisId: string,
    init?: RequestInit,
  ): Promise<RoundAnalysisTimeline>;
  getRoundAnalysisFrame(
    analysisId: string,
    packageId: string,
    partName: string,
    init?: RequestInit,
  ): Promise<Blob>;
  getRoundCounterfactual(
    analysisId: string,
    counterfactualId: string,
    init?: RequestInit,
  ): Promise<RoundCounterfactualResponse>;
}

export function createDokoDetectorClient(
  fetchImplementation: typeof fetch = fetch,
): DokoDetectorClient {
  return {
    listJobs: (options = {}) => {
      const query = new URLSearchParams();
      query.set("scope", options.scope ?? "active");
      query.set(
        "limit",
        String(Math.min(100, Math.max(1, options.limit ?? 50))),
      );
      if (options.cursor) query.set("cursor", options.cursor);
      return requestJson<JobListResponse>(
        fetchImplementation,
        `/api/jobs?${query}`,
        { signal: options.signal },
      );
    },
    getJobLogs: (jobId, options = {}) => {
      const query = new URLSearchParams();
      query.set(
        "limit",
        String(Math.min(500, Math.max(1, options.limit ?? 100))),
      );
      if (options.after !== undefined)
        query.set("after", String(Math.max(0, options.after)));
      return requestJson<JobLogPage>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/logs?${query}`,
        { signal: options.signal },
      );
    },
    cancelJob: (jobId, init) =>
      requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/cancel`,
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify({}),
        },
      ),
    enqueueJob: (payload, idempotencyKey, init) => {
      const headers = jsonHeaders(init?.headers);
      headers.set("Idempotency-Key", idempotencyKey);
      return requestJson<JobDetail>(fetchImplementation, "/api/jobs", {
        ...init,
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
    },
    getJob: (jobId, init) =>
      requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}`,
        init,
      ),
    getCalibrationPreview: (jobId, init) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/calibration-preview`,
        init,
      ),
    retryJob: (jobId, idempotencyKey, init) => {
      const headers = jsonHeaders(init?.headers);
      headers.set("Idempotency-Key", idempotencyKey);
      return requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/retry`,
        { ...init, method: "POST", headers, body: JSON.stringify({}) },
      );
    },
    moveJob: (groupId, beforeGroupId, expectedRevision) =>
      requestJson<components["schemas"]["QueueMoveResponse"]>(
        fetchImplementation,
        "/api/jobs/queue/move",
        {
          method: "POST",
          headers: jsonHeaders(undefined),
          body: JSON.stringify({
            group_id: groupId,
            before_group_id: beforeGroupId,
            expected_revision: expectedRevision,
          }),
        },
      ),
    startAutomatedPipelineRun: (recordingId, payload, init) =>
      requestJson<AutomatedPipelineRun>(
        fetchImplementation,
        `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/runs`,
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getAutomatedPipelineRun: (recordingId, runId, init) =>
      requestJson<AutomatedPipelineRun>(
        fetchImplementation,
        `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/runs/${encodeURIComponent(runId)}`,
        init,
      ),
    getFrameReviewPage: (options = {}) => {
      const params = new URLSearchParams();
      if (options.limit !== undefined)
        params.set("limit", String(options.limit));
      if (options.cursor !== undefined)
        params.set("cursor", String(options.cursor));
      if (options.state !== undefined) params.set("state", options.state);
      const query = params.toString();
      return requestJson<FrameReviewPageResponse>(
        fetchImplementation,
        `/api/frame-reviews/0096-M4${query === "" ? "" : `?${query}`}`,
        { signal: options.signal },
      );
    },
    updateFrameReviewWorkflow: (recordingId, itemId, payload, init) =>
      requestJson<FrameReviewWorkflowResponse>(
        fetchImplementation,
        `/api/frame-reviews/0096-M4/items/${encodeURIComponent(recordingId)}/${encodeURIComponent(itemId)}/workflow`,
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    listRecordings: (init) =>
      requestJson<RecordingListResponse>(
        fetchImplementation,
        recordingsPath(),
        init,
      ),
    getRecording: (recordingId, init) =>
      requestJson<RecordingDetail>(
        fetchImplementation,
        recordingDetailPath(recordingId),
        init,
      ),
    getRecordingPipeline: (recordingId, init, stageKey) =>
      requestJson<PipelineWorkspace>(
        fetchImplementation,
        recordingPipelineWorkspacePath(recordingId, stageKey),
        init,
      ),
    updatePipelineSelection: (recordingId, contentType, payload, init) =>
      requestJson<PipelineSelectionResponse>(
        fetchImplementation,
        recordingPipelineSelectionPath(recordingId, contentType),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    comparePipelineRuns: (recordingId, payload, init) =>
      requestJson<PipelineComparisonResponse>(
        fetchImplementation,
        pipelineComparisonPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startVisibleCardRun: (recordingId, payload, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisibleCardRunsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startProposedCardSceneRun: (recordingId, payload, init) =>
      requestJson<PipelineProposalRunResponse>(
        fetchImplementation,
        pipelineProposedCardSceneRunsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    listProposedCardSceneRuns: (recordingId, init) =>
      requestJson<{
        recording_id: string;
        runs: PipelineProposalRunResponse[];
      }>(
        fetchImplementation,
        pipelineProposedCardSceneRunsPath(recordingId),
        init,
      ),
    getProposedCardSceneResult: (recordingId, runId, init) =>
      requestJson<PipelineProposalResultResponse>(
        fetchImplementation,
        pipelineProposedCardSceneResultPath(recordingId, runId),
        init,
      ),
    startCalibrationRefinement: (recordingId, payload, init) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        pipelineCalibrationRefinementPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getCalibrationRefinement: (
      recordingId,
      proposalRevisionId,
      draftId,
      init,
    ) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        pipelineCalibrationRefinementReadPath(
          recordingId,
          proposalRevisionId,
          draftId,
        ),
        init,
      ),
    getPipelineCalibration: (recordingId, calibrationRevisionId, init) =>
      requestJson<PipelineCalibration>(
        fetchImplementation,
        pipelineCalibrationPath(recordingId, calibrationRevisionId),
        init,
      ),
    updateCalibrationRefinement: (
      recordingId,
      proposalRevisionId,
      payload,
      init,
    ) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        pipelineCalibrationRefinementReadPath(recordingId, proposalRevisionId),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    discardCalibrationRefinement: (recordingId, payload, init) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        pipelineCalibrationRefinementDiscardPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    applyCalibrationRefinement: (
      recordingId,
      proposalRevisionId,
      payload,
      init,
    ) =>
      requestJson<CalibrationRefinementApplyResponse>(
        fetchImplementation,
        pipelineCalibrationRefinementApplyPath(recordingId, proposalRevisionId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startVisualIdentityRun: (recordingId, payload, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisualIdentityRunsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    listVisualIdentityProposedCropInputs: (recordingId, init) =>
      requestJson(
        fetchImplementation,
        `${pipelineVisualIdentityRunsPath(recordingId)}/proposed-crop-inputs`,
        init,
      ),
    startObservationRun: (recordingId, payload, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineObservationRunsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getEventResult: (recordingId, runId, init) =>
      requestJson<PipelineEventResult>(
        fetchImplementation,
        pipelineEventResultPath(recordingId, runId),
        init,
      ),
    getVisibleCardResult: (recordingId, runId, init) =>
      requestJson<PipelineVisibleCardResult>(
        fetchImplementation,
        pipelineVisibleCardResultPath(recordingId, runId),
        init,
      ),
    getVisualIdentityResult: (recordingId, runId, init) =>
      requestJson<PipelineVisualIdentityResult>(
        fetchImplementation,
        pipelineVisualIdentityResultPath(recordingId, runId),
        init,
      ),
    startRecordingAnalysis: (recordingId, init) =>
      requestJson<RoundAnalysisStatus>(
        fetchImplementation,
        recordingAnalysisPath(recordingId),
        { ...init, method: "POST" },
      ),
    createRoundAnalysis: (payload, init) =>
      requestJson<RoundAnalysisStatus>(
        fetchImplementation,
        roundAnalysisPath(),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getRoundAnalysisStatus: (analysisId, init) =>
      requestJson<RoundAnalysisStatus>(
        fetchImplementation,
        roundAnalysisStatusPath(analysisId),
        init,
      ),
    getRoundAnalysisTimeline: (analysisId, init) =>
      requestJson<RoundAnalysisTimeline>(
        fetchImplementation,
        roundAnalysisTimelinePath(analysisId),
        init,
      ),
    getRoundAnalysisFrame: async (analysisId, packageId, partName, init) => {
      const response = await fetchImplementation(
        roundAnalysisFramePath(analysisId, packageId, partName),
        init,
      );
      if (!response.ok) {
        throw new ApiError(response.status, await readResponseBody(response));
      }
      return response.blob();
    },
    getRoundCounterfactual: (analysisId, counterfactualId, init) =>
      requestJson<RoundCounterfactualResponse>(
        fetchImplementation,
        roundCounterfactualReadPath(analysisId, counterfactualId),
        init,
      ),
  };
}

export function roundAnalysisFramePath(
  analysisId: string,
  packageId: string,
  partName: string,
): string {
  return `/v1/round-analyses/${encodeURIComponent(analysisId)}/evidence-packages/${encodeURIComponent(packageId)}/frames/${encodeURIComponent(partName)}`;
}

export function repositoryBundleVideoPath(recordingId: string): string {
  return `/v1/repository-bundles/${encodeURIComponent(recordingId)}/video`;
}

export function repositoryBundleThumbnailPath(recordingId: string): string {
  return `/v1/repository-bundles/${encodeURIComponent(recordingId)}/thumbnail`;
}

export function recordingAnalysisPath(recordingId: string): string {
  return `/v1/recordings/${encodeURIComponent(recordingId)}/round-analyses`;
}

export function recordingDetailPath(recordingId: string): string {
  return `/v1/recordings/${encodeURIComponent(recordingId)}`;
}

export function recordingPipelineWorkspacePath(
  recordingId: string,
  stageKey?: PipelineStageKey | null,
): string {
  const path = `/api/recordings/${encodeURIComponent(recordingId)}/pipeline`;
  return stageKey === undefined || stageKey === null
    ? path
    : `${path}?stage=${encodeURIComponent(stageKey)}`;
}

export function pipelineComparisonPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/comparisons`;
}

export function recordingPipelineSelectionPath(
  recordingId: string,
  contentType: PipelineSelectableContentType,
): string {
  const route =
    contentType === "events"
      ? "events"
      : contentType === "visible_cards"
        ? "visible-cards"
        : contentType === "visual_identities"
          ? "visual-identities"
          : "observations";
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/${route}/selection`;
}

export function pipelineEventResultPath(
  recordingId: string,
  runId: string,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/events/${encodeURIComponent(runId)}/result`;
}

export function pipelineVisibleCardRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visible-cards`;
}

export function pipelineProposedCardSceneRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/proposed-card-scenes`;
}

export function pipelineProposedCardSceneRunPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineProposedCardSceneRunsPath(recordingId)}/${encodeURIComponent(runId)}`;
}

export function pipelineProposedCardSceneResultPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineProposedCardSceneRunPath(recordingId, runId)}/result`;
}

export function pipelineCalibrationRefinementPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/calibration-refinement`;
}

export function pipelineCalibrationPath(
  recordingId: string,
  calibrationRevisionId: string,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/calibrations/${encodeURIComponent(calibrationRevisionId)}`;
}

export function pipelineCalibrationRefinementReadPath(
  recordingId: string,
  proposalRevisionId: string,
  draftId?: string,
): string {
  const query = new URLSearchParams({
    proposal_revision_id: proposalRevisionId,
  });
  if (draftId !== undefined) query.set("draft_id", draftId);
  return `${pipelineCalibrationRefinementPath(recordingId)}?${query.toString()}`;
}

export function pipelineCalibrationRefinementDiscardPath(
  recordingId: string,
): string {
  return `${pipelineCalibrationRefinementPath(recordingId)}/discard`;
}

export function pipelineCalibrationRefinementApplyPath(
  recordingId: string,
  proposalRevisionId: string,
): string {
  const query = new URLSearchParams({
    proposal_revision_id: proposalRevisionId,
  });
  return `${pipelineCalibrationRefinementPath(recordingId)}/apply?${query.toString()}`;
}

export function pipelineVisualIdentityRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visual-identities`;
}

export function pipelineObservationRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/observations`;
}

export function pipelineVisibleCardResultPath(
  recordingId: string,
  runId: string,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visible-cards/${encodeURIComponent(runId)}/result`;
}

export function pipelineVisualIdentityResultPath(
  recordingId: string,
  runId: string,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visual-identities/${encodeURIComponent(runId)}/result`;
}

export function pipelineIdentityCropPath(
  recordingId: string,
  revisionId: string,
  itemId: string,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/identity-crops/${encodeURIComponent(revisionId)}/${encodeURIComponent(itemId)}?preview=browser`;
}

export const SAMPLED_FRAME_INTERVAL_US = 250_000;

export function pipelineDerivedFramePath(
  recordingId: string,
  requestedTimeUs: number,
  frameIndex?: number,
): string {
  const path = `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/exact-event/${encodeURIComponent(String(Math.max(0, Math.round(requestedTimeUs))))}`;
  return frameIndex === undefined
    ? path
    : `${path}?frame_index=${encodeURIComponent(String(frameIndex))}`;
}

/** Snap to the same 250 ms ceiling the sampled-frame provider uses. */
export function snapSampledFrameTimeUs(requestedTimeUs: number): number {
  const timeUs = Number.isFinite(requestedTimeUs)
    ? Math.max(0, Math.round(requestedTimeUs))
    : 0;
  if (timeUs === 0) return 0;
  return (
    Math.ceil(timeUs / SAMPLED_FRAME_INTERVAL_US) * SAMPLED_FRAME_INTERVAL_US
  );
}

/** Fast scrub/review JPEG (250 ms samples, max 1280px). */
export function pipelineReviewFramePath(
  recordingId: string,
  requestedTimeUs: number,
): string {
  return `${pipelineDerivedFramePath(recordingId, snapSampledFrameTimeUs(requestedTimeUs))}?preview=sampled_250ms`;
}

function recordingsPath(): string {
  return "/v1/recordings";
}

function roundAnalysisStatusPath(analysisId: string): string {
  return `/v1/round-analyses/${encodeURIComponent(analysisId)}`;
}

function roundAnalysisPath(): string {
  return "/v1/round-analyses";
}

function roundAnalysisTimelinePath(analysisId: string): string {
  return `${roundAnalysisStatusPath(analysisId)}/timeline`;
}

export function roundCounterfactualPath(analysisId: string): string {
  return `${roundAnalysisStatusPath(analysisId)}/counterfactuals`;
}

export function roundCounterfactualReadPath(
  analysisId: string,
  counterfactualId: string,
): string {
  return `${roundCounterfactualPath(analysisId)}/${encodeURIComponent(counterfactualId)}`;
}
