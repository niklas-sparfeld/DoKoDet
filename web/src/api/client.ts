import type { paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type RoundAnalysisStatus = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}"]["get"]["responses"][200]
>;
export type RoundAnalysisTimeline = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}/timeline"]["get"]["responses"][200]
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
}

export function createDokoDetectorClient(
  fetchImplementation: typeof fetch = fetch,
): DokoDetectorClient {
  return {
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
  };
}

export function roundAnalysisFramePath(
  analysisId: string,
  packageId: string,
  partName: string,
): string {
  return `/v1/round-analyses/${encodeURIComponent(analysisId)}/evidence-packages/${encodeURIComponent(packageId)}/frames/${encodeURIComponent(partName)}`;
}

function roundAnalysisStatusPath(analysisId: string): string {
  return `/v1/round-analyses/${encodeURIComponent(analysisId)}`;
}

function roundAnalysisTimelinePath(analysisId: string): string {
  return `${roundAnalysisStatusPath(analysisId)}/timeline`;
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
