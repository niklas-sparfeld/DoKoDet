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
    | "set_frame_unreviewed"
    | "restore_frame_suggestions"
    | "set_frame_empty"
    | "set_frame_unusable"
    | "create_ignore_region"
    | "replace_ignore_region"
    | "delete_ignore_region"
    | "convert_to_ignore_region"
    | "accept_identity_suggestion"
    | "set_identity_unreviewed"
    | "set_identity_face_down"
    | "select_identity"
    | "set_identity_unusable"
    | "report_identity_source_problem";
  item_id?: string;
  item?: Record<string, unknown>;
  decision?: string;
  identity?: string;
  source_revision_id?: string;
  region_id?: string;
  region?: Record<string, unknown>;
  candidate_ids?: string[];
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
          decision:
            "cards" | "ignored" | "cards_and_ignored" | "empty" | "unusable";
        }>;
      }
    | {
        kind: "visual_identities";
        cards: Array<{
          card_id: string;
          decision: "identity" | "face_down" | "unusable" | "source_problem";
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
export type PipelineVisibleCardResult = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/visible-cards/{run_id}/result"]["get"]["responses"][200]
>;
export type PipelineVisualIdentityResult = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}/result"]["get"]["responses"][200]
>;
export type RecordingSummary = RecordingListResponse["recordings"][number];
export type RecordingAnalysisSummary = RecordingSummary["analyses"][number];
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

export function repositoryBundleThumbnailPath(recordingId: string): string {
  return `/v1/repository-bundles/${encodeURIComponent(recordingId)}/thumbnail`;
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
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/identity-crops/${encodeURIComponent(revisionId)}/${encodeURIComponent(itemId)}?preview=browser`;
}

export function pipelineDerivedFramePath(
  recordingId: string,
  requestedTimeUs: number,
): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/exact-event/${encodeURIComponent(String(Math.max(0, Math.round(requestedTimeUs))))}`;
}

export function pipelineReviewFramePath(
  recordingId: string,
  requestedTimeUs: number,
): string {
  return `${pipelineDerivedFramePath(recordingId, requestedTimeUs)}?preview=sampled_250ms`;
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
