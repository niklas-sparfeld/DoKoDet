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
import type {
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
