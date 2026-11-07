import type { DokoDetectorClient } from "./clientTypes";
import type {
  AutomatedPipelineRun,
  PipelineComparisonResponse,
  PipelineEventResult,
  PipelineProposalResultResponse,
  PipelineProposalRunResponse,
  PipelineRunResponse,
  PipelineSelectableContentType,
  PipelineSelectionResponse,
  PipelineStageKey,
  PipelineVisibleCardResult,
  PipelineVisualIdentityResult,
  PipelineWorkspace,
} from "./pipelineContracts";

import { jsonHeaders, requestJson } from "./transport";

export function createPipelineProcessingClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<
  DokoDetectorClient,
  | "startAutomatedPipelineRun"
  | "getRecordingPipeline"
  | "updatePipelineSelection"
  | "comparePipelineRuns"
  | "listProposedCardSceneRuns"
  | "getProposedCardSceneResult"
  | "startVisualIdentityRun"
  | "listVisualIdentityProposedCropInputs"
  | "getEventResult"
  | "getVisibleCardResult"
  | "getVisualIdentityResult"
> {
  return {
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
  };
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

export function pipelineVisualIdentityRunsPath(recordingId: string): string {
  return `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/visual-identities`;
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
  frameIndex?: number,
): string {
  const path = `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/derived-views/exact-event/${encodeURIComponent(String(Math.max(0, Math.round(requestedTimeUs))))}`;
  return frameIndex === undefined
    ? path
    : `${path}?frame_index=${encodeURIComponent(String(frameIndex))}`;
}

/** Snap to the same 250 ms ceiling the sampled-frame provider uses. */

export function pipelineReviewFramePath(
  recordingId: string,
  requestedTimeUs: number,
): string {
  return `${pipelineDerivedFramePath(recordingId, snapSampledFrameTimeUs(requestedTimeUs))}?preview=sampled_250ms`;
}

export const SAMPLED_FRAME_INTERVAL_US = 250_000;

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
