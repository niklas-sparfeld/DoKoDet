import type { DokoDetectorClient } from "./clientTypes";
import { ApiError, readResponseBody } from "./transport";
import type {
  RoundAnalysisStatus,
  RoundAnalysisTimeline,
  RoundCounterfactualResponse,
} from "./analysisContracts";

import { jsonHeaders, requestJson } from "./transport";

export function createAnalysisClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<
  DokoDetectorClient,
  | "createRoundAnalysis"
  | "getRoundAnalysisStatus"
  | "getRoundAnalysisTimeline"
  | "getRoundAnalysisFrame"
  | "getRoundCounterfactual"
> {
  return {
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

export function roundCounterfactualPath(analysisId: string): string {
  return `${roundAnalysisStatusPath(analysisId)}/counterfactuals`;
}

export function roundCounterfactualReadPath(
  analysisId: string,
  counterfactualId: string,
): string {
  return `${roundCounterfactualPath(analysisId)}/${encodeURIComponent(counterfactualId)}`;
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
