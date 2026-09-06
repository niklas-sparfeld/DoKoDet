import type { components, paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type RoundAnalysisStatus = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}"]["get"]["responses"][200]
>;
export type RecordingListResponse = JsonResponse<
  paths["/v1/recordings"]["get"]["responses"][200]
>;
export type RecordingDetail = JsonResponse<
  paths["/v1/recordings/{recording_id}"]["get"]["responses"][200]
>;
export type PipelineWorkspace = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline"]["get"]["responses"][200]
>;
export type PipelineWorkspaceStage = PipelineWorkspace["stages"][number];
export type PipelineRun = PipelineWorkspaceStage["runs"][number];
export type PipelineCompatibleInputSet =
  PipelineWorkspaceStage["compatible_input_sets"][number];
export type PipelineStageKey = PipelineWorkspaceStage["key"];
export type PipelineSelectableContentType = Exclude<
  PipelineStageKey,
  "round_analyses"
>;
export type PipelineSelectionUpdateRequest = {
  expected_revision: number;
  selected_generated_revision_id: string | null;
};
export type PipelineSelection = {
  revision: number;
  recording_id: string;
  content_type: PipelineSelectableContentType;
  selected_generated_revision_id: string | null;
  selected_completed_reference_revision_id: string | null;
  updated_at: string;
};
export type PipelineSelectionResponse = {
  recording_id: string;
  selection: PipelineSelection;
};
export type PipelineRunStartRequest = {
  request: {
    run_id: string;
    input_revision_ids?: string[];
    event_revision_id?: string;
    visible_card_revision_id?: string;
    processor_type?: string;
    implementation?: { name: string; version: string };
    model?: Record<string, unknown> | null;
    configuration?: Record<string, unknown>;
    extraction_policy?: Record<string, unknown>;
    crop_policy?: Record<string, unknown> | null;
  };
};
export type PipelineRunResponse = {
  run_id: string;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
};
export type RoundAnalysisCreateRequest =
  components["schemas"]["RoundAnalysisCreateRequest"];
export type PipelineComparisonRequest =
  components["schemas"]["PipelineComparisonRequest"];
export type PipelineComparisonResponse = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/comparisons"]["post"]["responses"][200]
>;
export type PipelineReferenceItem = {
  item_id: string;
  base_item_id: string | null;
  review_state: string;
  item: Record<string, unknown>;
};
export type PipelineReferenceResource = {
  recording_id: string;
  content_type: PipelineSelectableContentType;
  state: {
    recording_id: string;
    content_type: PipelineSelectableContentType;
    draft_revision: number;
    draft_state: "draft" | "completed";
    source_revision_id: string | null;
    selected_completed_revision_id: string | null;
    updated_at: string;
  };
  draft: {
    recording_id: string;
    content_type: PipelineSelectableContentType;
    revision: number;
    source_revision_id: string | null;
    items: PipelineReferenceItem[];
    coverage: Record<string, unknown> | null;
    impact: Array<Record<string, unknown>>;
    updated_at: string;
  };
};
export type PipelineReferenceCreateRequest = {
  operator_id: string;
  seed?: "selected_generated" | "selected_completed" | "empty";
  source_revision_id?: string;
};
export type PipelineReferenceOperation = {
  operation:
    | "accept"
    | "reject"
    | "add"
    | "correct"
    | "decide"
    | "rebase"
    | "set_frame_review"
    | "accept_frame_suggestions"
    | "set_frame_empty"
    | "set_frame_unusable"
    | "accept_identity_suggestion"
    | "select_identity"
    | "set_identity_unusable"
    | "report_identity_source_problem";
  item_id?: string;
  item?: Record<string, unknown>;
  decision?: string;
  identity?: string;
  source_revision_id?: string;
};
export type PipelineReferenceDraftUpdateRequest = {
  expected_revision: number;
  operator_id: string;
  command_id?: string;
  operations: PipelineReferenceOperation[];
};
export type PipelineReferenceCompletionRequest = {
  expected_revision: number;
  operator_id: string;
  coverage:
    | {
        kind: "full_recording";
        intervals: Array<{ start_us: number; end_us: number }>;
      }
    | {
        kind: "visible_frames";
        frames: Array<{
          item_id?: string;
          frame_identity: Record<string, unknown> | null;
          decision: "cards" | "empty" | "unusable";
        }>;
      }
    | {
        kind: "identity_cards";
        cards: Array<{
          card_id: string;
          decision: "identity" | "unusable";
        }>;
      };
};
export type PipelineEventResult = {
  run_id: string;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  revisions: Array<{
    manifest: Record<string, unknown>;
    content: {
      schema_version?: string;
      events?: Array<Record<string, unknown>>;
    };
  }>;
};
export type PipelineVisibleCardResult = {
  run_id: string;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  revisions: Array<{
    manifest: Record<string, unknown>;
    content: {
      schema_version?: string;
      outcomes?: Array<Record<string, unknown>>;
    };
  }>;
};
export type PipelineVisualIdentityResult = {
  run_id: string;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  revisions: Array<{
    manifest: Record<string, unknown>;
    content: {
      schema_version?: string;
      outcomes?: Array<Record<string, unknown>>;
    };
  }>;
};
export type RecordingSummary = RecordingListResponse["recordings"][number];
export type RecordingAnalysisSummary = RecordingSummary["analyses"][number];
export type CardEventReview = JsonResponse<
  paths["/v1/recordings/{recording_id}/card-event-review"]["get"]["responses"][200]
>;
export type CardEventReviewCollection = JsonResponse<
  paths["/v1/recordings/{recording_id}/card-event-reviews"]["get"]["responses"][200]
>;
export type CardEventReviewResource = JsonResponse<
  paths["/v1/card-event-reviews/{review_id}"]["get"]["responses"][200]
>;
export type CardEvent = components["schemas"]["CardEventResponse"];
export type CardEventCreateRequest =
  components["schemas"]["CardEventCreateRequest"];
export type CardEventCommandRequest =
  components["schemas"]["CardEventCommandRequest"];
export type CardEventCommandResponse = JsonResponse<
  paths["/v1/card-event-reviews/{review_id}/events"]["post"]["responses"][200]
>;
export type CardEventReviewCreateRequest =
  components["schemas"]["CardEventReviewCreateRequest"];
export type CardEventReviewResourceUpdateRequest =
  components["schemas"]["CardEventReviewResourceUpdateRequest"];
export type CardEventReviewDraftUpdateRequest =
  components["schemas"]["CardEventReviewDraftUpdateRequest"];
export type CardEventReviewCompletionRequest =
  components["schemas"]["CardEventReviewCompletionRequest"];
export type CardEventReviewRevisionRequest =
  components["schemas"]["CardEventReviewRevisionRequest"];
export type CardEventDevelopmentSplitPreviewRequest =
  components["schemas"]["CardEventDevelopmentSplitPreviewRequest"];
export type CardEventDevelopmentSplitPreview = JsonResponse<
  paths["/v1/data/cardevent-development-split/preview"]["post"]["responses"][200]
>;
export type CardEventDevelopmentSplitApplyRequest =
  components["schemas"]["CardEventDevelopmentSplitApplyRequest"];
export type CardEventDevelopmentSplitApply = JsonResponse<
  paths["/v1/data/cardevent-development-split/apply"]["post"]["responses"][200]
>;
export type VisibleCardReviewReadiness = JsonResponse<
  paths["/v1/recordings/{recording_id}/visible-card-review"]["get"]["responses"][200]
>;
export type VisibleCardReviewPreview = JsonResponse<
  paths["/v1/recordings/{recording_id}/visible-card-review/preview"]["post"]["responses"][200]
>;
export type VisibleCardReviewCreateRequest =
  components["schemas"]["VisibleCardReviewCreateRequest"];
export type VisibleCardReviewBatch = JsonResponse<
  paths["/v1/visible-card-reviews/{batch_id}"]["get"]["responses"][200]
>;
export type VisibleCardReviewItemUpdateRequest =
  components["schemas"]["VisibleCardReviewItemUpdateRequest"];
export type VisibleCardReviewItemRedetectRequest =
  components["schemas"]["VisibleCardReviewItemRedetectRequest"];
export type VisibleCardReviewCompletionRequest =
  components["schemas"]["VisibleCardReviewCompletionRequest"];
export type VisibleCardReviewRevisionRequest =
  components["schemas"]["VisibleCardReviewRevisionRequest"];
export type IdentityReviewReadiness = JsonResponse<
  paths["/v1/recordings/{recording_id}/identity-review"]["get"]["responses"][200]
>;
export type IdentityReviewPreview = JsonResponse<
  paths["/v1/recordings/{recording_id}/identity-review/preview"]["post"]["responses"][200]
>;
export type IdentityReviewPreviewRequest =
  components["schemas"]["IdentityReviewPreviewRequest"];
export type IdentityReviewCreateRequest =
  components["schemas"]["IdentityReviewCreateRequest"];
export type IdentityReviewBatch = JsonResponse<
  paths["/v1/identity-reviews/{batch_id}"]["get"]["responses"][200]
>;
export type IdentityDecisionUpdateRequest =
  components["schemas"]["IdentityDecisionUpdateRequest"];
export type IdentityReviewCompletionRequest =
  components["schemas"]["IdentityReviewCompletionRequest"];
export type IdentityReviewRevisionRequest =
  components["schemas"]["IdentityReviewRevisionRequest"];
export type RoundAnalysisTimeline = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}/timeline"]["get"]["responses"][200]
>;
export type RoundCounterfactualCreateRequest =
  components["schemas"]["RoundCounterfactualCreateRequest"];
export type RoundCounterfactualResponse = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}/counterfactuals"]["post"]["responses"][201]
>;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`DokoDetector API request failed with status ${status}.`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface DokoDetectorClient {
  listRecordings(init?: RequestInit): Promise<RecordingListResponse>;
  getRecording(
    recordingId: string,
    init?: RequestInit,
  ): Promise<RecordingDetail>;
  getRecordingPipeline(
    recordingId: string,
    init?: RequestInit,
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
  startEventRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  getEventRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  retryEventRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  startVisibleCardRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  getVisibleCardRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  retryVisibleCardRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  startVisualIdentityRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  getVisualIdentityRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  retryVisualIdentityRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  startObservationRun(
    recordingId: string,
    payload: PipelineRunStartRequest,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  getObservationRun(
    recordingId: string,
    runId: string,
    init?: RequestInit,
  ): Promise<PipelineRunResponse>;
  retryObservationRun(
    recordingId: string,
    runId: string,
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
  getPipelineReference(
    recordingId: string,
    contentType: PipelineSelectableContentType,
    init?: RequestInit,
  ): Promise<PipelineReferenceResource>;
  createPipelineReference(
    recordingId: string,
    contentType: PipelineSelectableContentType,
    payload: PipelineReferenceCreateRequest,
    init?: RequestInit,
  ): Promise<PipelineReferenceResource>;
  updatePipelineReferenceDraft(
    recordingId: string,
    contentType: PipelineSelectableContentType,
    payload: PipelineReferenceDraftUpdateRequest,
    init?: RequestInit,
  ): Promise<PipelineReferenceResource>;
  completePipelineReference(
    recordingId: string,
    contentType: PipelineSelectableContentType,
    payload: PipelineReferenceCompletionRequest,
    init?: RequestInit,
  ): Promise<PipelineReferenceResource>;
  getCardEventReview(
    recordingId: string,
    init?: RequestInit,
  ): Promise<CardEventReview>;
  listCardEventReviews(
    recordingId: string,
    init?: RequestInit,
  ): Promise<CardEventReviewCollection>;
  createCardEventReview(
    recordingId: string,
    payload: CardEventReviewCreateRequest,
    init?: RequestInit,
  ): Promise<CardEventReviewResource>;
  getCardEventReviewResource(
    reviewId: string,
    init?: RequestInit,
  ): Promise<CardEventReviewResource>;
  addCardEvent(
    reviewId: string,
    payload: CardEventCreateRequest,
    init?: RequestInit,
  ): Promise<CardEventCommandResponse>;
  updateCardEvent(
    reviewId: string,
    eventId: string,
    payload: CardEventCommandRequest,
    init?: RequestInit,
  ): Promise<CardEventCommandResponse>;
  updateCardEventReviewResource(
    reviewId: string,
    payload: CardEventReviewResourceUpdateRequest,
    init?: RequestInit,
  ): Promise<CardEventReviewResource>;
  completeCardEventReviewResource(
    reviewId: string,
    payload: CardEventReviewCompletionRequest,
    init?: RequestInit,
  ): Promise<CardEventReviewResource>;
  updateCardEventReviewDraft(
    recordingId: string,
    payload: CardEventReviewDraftUpdateRequest,
    init?: RequestInit,
  ): Promise<CardEventReview>;
  completeCardEventReview(
    recordingId: string,
    payload: CardEventReviewCompletionRequest,
    init?: RequestInit,
  ): Promise<CardEventReview>;
  startCardEventReviewRevision(
    recordingId: string,
    payload: CardEventReviewRevisionRequest,
    init?: RequestInit,
  ): Promise<CardEventReview>;
  previewCardEventDevelopmentSplit(
    payload: CardEventDevelopmentSplitPreviewRequest,
    init?: RequestInit,
  ): Promise<CardEventDevelopmentSplitPreview>;
  applyCardEventDevelopmentSplit(
    payload: CardEventDevelopmentSplitApplyRequest,
    init?: RequestInit,
  ): Promise<CardEventDevelopmentSplitApply>;
  getVisibleCardReview(
    recordingId: string,
    init?: RequestInit,
  ): Promise<VisibleCardReviewReadiness>;
  previewVisibleCardReview(
    recordingId: string,
    init?: RequestInit,
  ): Promise<VisibleCardReviewPreview>;
  createVisibleCardReviewBatch(
    recordingId: string,
    payload: VisibleCardReviewCreateRequest,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  getVisibleCardReviewBatch(
    batchId: string,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  getVisibleCardReviewItemImage(
    batchId: string,
    itemId: string,
    init?: RequestInit,
  ): Promise<Blob>;
  updateVisibleCardReviewItem(
    batchId: string,
    itemId: string,
    payload: VisibleCardReviewItemUpdateRequest,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  redetectVisibleCardReviewItem(
    batchId: string,
    itemId: string,
    payload: VisibleCardReviewItemRedetectRequest,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  retryVisibleCardReviewBatch(
    batchId: string,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  completeVisibleCardReviewBatch(
    batchId: string,
    payload: VisibleCardReviewCompletionRequest,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  startVisibleCardReviewRevision(
    batchId: string,
    payload: VisibleCardReviewRevisionRequest,
    init?: RequestInit,
  ): Promise<VisibleCardReviewBatch>;
  getIdentityReview(
    recordingId: string,
    init?: RequestInit,
  ): Promise<IdentityReviewReadiness>;
  previewIdentityReview(
    recordingId: string,
    payload?: IdentityReviewPreviewRequest,
    init?: RequestInit,
  ): Promise<IdentityReviewPreview>;
  createIdentityReviewBatch(
    recordingId: string,
    payload: IdentityReviewCreateRequest,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
  getIdentityReviewBatch(
    batchId: string,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
  getIdentityReviewCrop(
    batchId: string,
    itemId: string,
    init?: RequestInit,
  ): Promise<Blob>;
  retryIdentityReviewBatch(
    batchId: string,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
  updateIdentityReviewItem(
    batchId: string,
    itemId: string,
    payload: IdentityDecisionUpdateRequest,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
  completeIdentityReviewBatch(
    batchId: string,
    payload: IdentityReviewCompletionRequest,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
  startIdentityReviewRevision(
    batchId: string,
    payload: IdentityReviewRevisionRequest,
    init?: RequestInit,
  ): Promise<IdentityReviewBatch>;
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
  createRoundCounterfactual(
    analysisId: string,
    payload: RoundCounterfactualCreateRequest,
    init?: RequestInit,
  ): Promise<RoundCounterfactualResponse>;
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
    getRecordingPipeline: (recordingId, init) =>
      requestJson<PipelineWorkspace>(
        fetchImplementation,
        recordingPipelineWorkspacePath(recordingId),
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
    startEventRun: (recordingId, payload, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineEventRunsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getEventRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineEventRunPath(recordingId, runId),
        init,
      ),
    retryEventRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineEventRunRetryPath(recordingId, runId),
        { ...init, method: "POST" },
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
    getVisibleCardRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisibleCardRunPath(recordingId, runId),
        init,
      ),
    retryVisibleCardRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisibleCardRunRetryPath(recordingId, runId),
        { ...init, method: "POST" },
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
    getVisualIdentityRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisualIdentityRunPath(recordingId, runId),
        init,
      ),
    retryVisualIdentityRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineVisualIdentityRunRetryPath(recordingId, runId),
        { ...init, method: "POST" },
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
    getObservationRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineObservationRunPath(recordingId, runId),
        init,
      ),
    retryObservationRun: (recordingId, runId, init) =>
      requestJson<PipelineRunResponse>(
        fetchImplementation,
        pipelineObservationRunRetryPath(recordingId, runId),
        { ...init, method: "POST" },
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
    getPipelineReference: (recordingId, contentType, init) =>
      requestJson<PipelineReferenceResource>(
        fetchImplementation,
        pipelineReferencePath(recordingId, contentType),
        init,
      ),
    createPipelineReference: (recordingId, contentType, payload, init) =>
      requestJson<PipelineReferenceResource>(
        fetchImplementation,
        pipelineReferencePath(recordingId, contentType),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    updatePipelineReferenceDraft: (recordingId, contentType, payload, init) =>
      requestJson<PipelineReferenceResource>(
        fetchImplementation,
        pipelineReferenceDraftPath(recordingId, contentType),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    completePipelineReference: (recordingId, contentType, payload, init) =>
      requestJson<PipelineReferenceResource>(
        fetchImplementation,
        pipelineReferenceCompletionPath(recordingId, contentType),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getCardEventReview: (recordingId, init) =>
      requestJson<CardEventReview>(
        fetchImplementation,
        recordingCardEventReviewPath(recordingId),
        init,
      ),
    listCardEventReviews: (recordingId, init) =>
      requestJson<CardEventReviewCollection>(
        fetchImplementation,
        recordingCardEventReviewsPath(recordingId),
        init,
      ),
    createCardEventReview: (recordingId, payload, init) =>
      requestJson<CardEventReviewResource>(
        fetchImplementation,
        recordingCardEventReviewsPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getCardEventReviewResource: (reviewId, init) =>
      requestJson<CardEventReviewResource>(
        fetchImplementation,
        cardEventReviewResourcePath(reviewId),
        init,
      ),
    addCardEvent: (reviewId, payload, init) =>
      requestJson<CardEventCommandResponse>(
        fetchImplementation,
        cardEventReviewEventsPath(reviewId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    updateCardEvent: (reviewId, eventId, payload, init) =>
      requestJson<CardEventCommandResponse>(
        fetchImplementation,
        cardEventReviewEventPath(reviewId, eventId),
        {
          ...init,
          method: "PATCH",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    updateCardEventReviewResource: (reviewId, payload, init) =>
      requestJson<CardEventReviewResource>(
        fetchImplementation,
        cardEventReviewResourcePath(reviewId),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    completeCardEventReviewResource: (reviewId, payload, init) =>
      requestJson<CardEventReviewResource>(
        fetchImplementation,
        cardEventReviewResourceCompletionPath(reviewId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    updateCardEventReviewDraft: (recordingId, payload, init) =>
      requestJson<CardEventReview>(
        fetchImplementation,
        recordingCardEventReviewDraftPath(recordingId),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    completeCardEventReview: (recordingId, payload, init) =>
      requestJson<CardEventReview>(
        fetchImplementation,
        recordingCardEventReviewCompletionPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startCardEventReviewRevision: (recordingId, payload, init) =>
      requestJson<CardEventReview>(
        fetchImplementation,
        recordingCardEventReviewRevisionPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    previewCardEventDevelopmentSplit: (payload, init) =>
      requestJson<CardEventDevelopmentSplitPreview>(
        fetchImplementation,
        cardEventDevelopmentSplitPreviewPath(),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    applyCardEventDevelopmentSplit: (payload, init) =>
      requestJson<CardEventDevelopmentSplitApply>(
        fetchImplementation,
        cardEventDevelopmentSplitApplyPath(),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getVisibleCardReview: (recordingId, init) =>
      requestJson<VisibleCardReviewReadiness>(
        fetchImplementation,
        visibleCardReviewReadinessPath(recordingId),
        init,
      ),
    previewVisibleCardReview: (recordingId, init) =>
      requestJson<VisibleCardReviewPreview>(
        fetchImplementation,
        visibleCardReviewPreviewPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify({}),
        },
      ),
    createVisibleCardReviewBatch: (recordingId, payload, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewBatchCreatePath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getVisibleCardReviewBatch: (batchId, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewBatchPath(batchId),
        init,
      ),
    getVisibleCardReviewItemImage: async (batchId, itemId, init) => {
      const response = await fetchImplementation(
        visibleCardReviewItemImagePath(batchId, itemId),
        init,
      );
      if (!response.ok) {
        throw new ApiError(response.status, await readResponseBody(response));
      }
      return response.blob();
    },
    updateVisibleCardReviewItem: (batchId, itemId, payload, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewItemPath(batchId, itemId),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    redetectVisibleCardReviewItem: (batchId, itemId, payload, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewItemRedetectPath(batchId, itemId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    retryVisibleCardReviewBatch: (batchId, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewBatchRetryPath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify({}),
        },
      ),
    completeVisibleCardReviewBatch: (batchId, payload, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewBatchCompletePath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startVisibleCardReviewRevision: (batchId, payload, init) =>
      requestJson<VisibleCardReviewBatch>(
        fetchImplementation,
        visibleCardReviewBatchRevisionPath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getIdentityReview: (recordingId, init) =>
      requestJson<IdentityReviewReadiness>(
        fetchImplementation,
        identityReviewReadinessPath(recordingId),
        init,
      ),
    previewIdentityReview: (recordingId, payload, init) =>
      requestJson<IdentityReviewPreview>(
        fetchImplementation,
        identityReviewPreviewPath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload ?? {}),
        },
      ),
    createIdentityReviewBatch: (recordingId, payload, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewBatchCreatePath(recordingId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    getIdentityReviewBatch: (batchId, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewBatchPath(batchId),
        init,
      ),
    getIdentityReviewCrop: async (batchId, itemId, init) => {
      const response = await fetchImplementation(
        identityReviewCropPath(batchId, itemId),
        init,
      );
      if (!response.ok) {
        throw new ApiError(response.status, await readResponseBody(response));
      }
      return response.blob();
    },
    retryIdentityReviewBatch: (batchId, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewBatchRetryPath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify({}),
        },
      ),
    updateIdentityReviewItem: (batchId, itemId, payload, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewItemPath(batchId, itemId),
        {
          ...init,
          method: "PUT",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    completeIdentityReviewBatch: (batchId, payload, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewBatchCompletePath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
    startIdentityReviewRevision: (batchId, payload, init) =>
      requestJson<IdentityReviewBatch>(
        fetchImplementation,
        identityReviewBatchRevisionPath(batchId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
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
    createRoundCounterfactual: (analysisId, payload, init) =>
      requestJson<RoundCounterfactualResponse>(
        fetchImplementation,
        roundCounterfactualPath(analysisId),
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify(payload),
        },
      ),
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

export function recordingAnalysisPath(recordingId: string): string {
  return `/v1/recordings/${encodeURIComponent(recordingId)}/round-analyses`;
}

export function recordingDetailPath(recordingId: string): string {
  return `/v1/recordings/${encodeURIComponent(recordingId)}`;
}

export function recordingPipelineWorkspacePath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline`;
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

export function pipelineEventRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/events`;
}

export function pipelineEventRunPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineEventRunsPath(recordingId)}/${encodeURIComponent(runId)}`;
}

export function pipelineEventRunRetryPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineEventRunPath(recordingId, runId)}/retry`;
}

export function pipelineVisibleCardRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visible-cards`;
}

export function pipelineVisibleCardRunPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineVisibleCardRunsPath(recordingId)}/${encodeURIComponent(runId)}`;
}

export function pipelineVisibleCardRunRetryPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineVisibleCardRunPath(recordingId, runId)}/retry`;
}

export function pipelineVisualIdentityRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visual-identities`;
}

export function pipelineVisualIdentityRunPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineVisualIdentityRunsPath(recordingId)}/${encodeURIComponent(runId)}`;
}

export function pipelineVisualIdentityRunRetryPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineVisualIdentityRunPath(recordingId, runId)}/retry`;
}

export function pipelineObservationRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/observations`;
}

export function pipelineObservationRunPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineObservationRunsPath(recordingId)}/${encodeURIComponent(runId)}`;
}

export function pipelineObservationRunRetryPath(
  recordingId: string,
  runId: string,
): string {
  return `${pipelineObservationRunPath(recordingId, runId)}/retry`;
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
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/identity-crops/${encodeURIComponent(revisionId)}/${encodeURIComponent(itemId)}`;
}

export function pipelineDerivedFramePath(
  recordingId: string,
  requestedTimeUs: number,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/exact-event/${encodeURIComponent(String(Math.max(0, Math.round(requestedTimeUs))))}`;
}

export function pipelineReferencePath(
  recordingId: string,
  contentType: PipelineSelectableContentType,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/references/${encodeURIComponent(contentType)}`;
}

export function pipelineReferenceDraftPath(
  recordingId: string,
  contentType: PipelineSelectableContentType,
): string {
  return `${pipelineReferencePath(recordingId, contentType)}/draft`;
}

export function pipelineReferenceCompletionPath(
  recordingId: string,
  contentType: PipelineSelectableContentType,
): string {
  return `${pipelineReferencePath(recordingId, contentType)}/complete`;
}

export function recordingCardEventReviewPath(recordingId: string): string {
  return `${recordingDetailPath(recordingId)}/card-event-review`;
}

export function recordingCardEventReviewsPath(recordingId: string): string {
  return `${recordingDetailPath(recordingId)}/card-event-reviews`;
}

export function cardEventReviewResourcePath(reviewId: string): string {
  return `/v1/card-event-reviews/${encodeURIComponent(reviewId)}`;
}

export function cardEventReviewResourceCompletionPath(
  reviewId: string,
): string {
  return `${cardEventReviewResourcePath(reviewId)}/complete`;
}

export function cardEventReviewEventsPath(reviewId: string): string {
  return `${cardEventReviewResourcePath(reviewId)}/events`;
}

export function cardEventReviewEventPath(
  reviewId: string,
  eventId: string,
): string {
  return `${cardEventReviewEventsPath(reviewId)}/${encodeURIComponent(eventId)}`;
}

export function recordingCardEventReviewDraftPath(recordingId: string): string {
  return `${recordingCardEventReviewPath(recordingId)}/draft`;
}

export function recordingCardEventReviewCompletionPath(
  recordingId: string,
): string {
  return `${recordingCardEventReviewPath(recordingId)}/complete`;
}

export function recordingCardEventReviewRevisionPath(
  recordingId: string,
): string {
  return `${recordingCardEventReviewPath(recordingId)}/revisions`;
}

export function visibleCardReviewReadinessPath(recordingId: string): string {
  return `${recordingDetailPath(recordingId)}/visible-card-review`;
}

export function visibleCardReviewPreviewPath(recordingId: string): string {
  return `${visibleCardReviewReadinessPath(recordingId)}/preview`;
}

export function visibleCardReviewBatchCreatePath(recordingId: string): string {
  return `${visibleCardReviewReadinessPath(recordingId)}/batches`;
}

export function visibleCardReviewBatchPath(batchId: string): string {
  return `/v1/visible-card-reviews/${encodeURIComponent(batchId)}`;
}

export function visibleCardReviewBatchPagePath(batchId: string): string {
  return `/visible-card-reviews/${encodeURIComponent(batchId)}`;
}

export function visibleCardReviewItemImagePath(
  batchId: string,
  itemId: string,
): string {
  return `${visibleCardReviewBatchPath(batchId)}/items/${encodeURIComponent(itemId)}/image`;
}

export function visibleCardReviewItemPath(
  batchId: string,
  itemId: string,
): string {
  return `${visibleCardReviewBatchPath(batchId)}/items/${encodeURIComponent(itemId)}`;
}

export function visibleCardReviewItemRedetectPath(
  batchId: string,
  itemId: string,
): string {
  return `${visibleCardReviewItemPath(batchId, itemId)}/redetect`;
}

export function visibleCardReviewBatchRetryPath(batchId: string): string {
  return `${visibleCardReviewBatchPath(batchId)}/retry`;
}

export function visibleCardReviewBatchCompletePath(batchId: string): string {
  return `${visibleCardReviewBatchPath(batchId)}/complete`;
}

export function visibleCardReviewBatchRevisionPath(batchId: string): string {
  return `${visibleCardReviewBatchPath(batchId)}/revisions`;
}

export function identityReviewReadinessPath(recordingId: string): string {
  return `${recordingDetailPath(recordingId)}/identity-review`;
}

export function identityReviewPreviewPath(recordingId: string): string {
  return `${identityReviewReadinessPath(recordingId)}/preview`;
}

export function identityReviewBatchCreatePath(recordingId: string): string {
  return `${identityReviewReadinessPath(recordingId)}/batches`;
}

export function identityReviewBatchPath(batchId: string): string {
  return `/v1/identity-reviews/${encodeURIComponent(batchId)}`;
}

export function identityReviewBatchPagePath(batchId: string): string {
  return `/identity-reviews/${encodeURIComponent(batchId)}`;
}

export function identityReviewCropPath(
  batchId: string,
  itemId: string,
): string {
  return `${identityReviewBatchPath(batchId)}/items/${encodeURIComponent(itemId)}/crop`;
}

export function identityReviewBatchRetryPath(batchId: string): string {
  return `${identityReviewBatchPath(batchId)}/retry`;
}

export function identityReviewItemPath(
  batchId: string,
  itemId: string,
): string {
  return `${identityReviewBatchPath(batchId)}/items/${encodeURIComponent(itemId)}`;
}

export function identityReviewBatchCompletePath(batchId: string): string {
  return `${identityReviewBatchPath(batchId)}/complete`;
}

export function identityReviewBatchRevisionPath(batchId: string): string {
  return `${identityReviewBatchPath(batchId)}/revisions`;
}

export function cardEventDevelopmentSplitPreviewPath(): string {
  return "/v1/data/cardevent-development-split/preview";
}

export function cardEventDevelopmentSplitApplyPath(): string {
  return "/v1/data/cardevent-development-split/apply";
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

async function requestJson<Response>(
  fetchImplementation: typeof fetch,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetchImplementation(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readResponseBody(response));
  }
  return (await response.json()) as Response;
}

function jsonHeaders(headers: HeadersInit | undefined): Headers {
  const result = new Headers(headers);
  result.set("Accept", "application/json");
  result.set("Content-Type", "application/json");
  return result;
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}
