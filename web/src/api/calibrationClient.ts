import type { DokoDetectorClient } from "./clientTypes";
import type {
  CalibrationRefinementApplyResponse,
  CalibrationRefinementResponse,
  PipelineCalibration,
} from "./calibrationContracts";

import { jsonHeaders, requestJson } from "./transport";

export function createCalibrationClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<
  DokoDetectorClient,
  | "getCalibrationRefinement"
  | "getPipelineCalibration"
  | "updateCalibrationRefinement"
  | "discardCalibrationRefinement"
  | "applyCalibrationRefinement"
> {
  return {
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
  };
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
