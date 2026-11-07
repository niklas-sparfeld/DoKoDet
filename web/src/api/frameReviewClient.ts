import type { DokoDetectorClient } from "./clientTypes";
import type {
  FrameReviewPageResponse,
  FrameReviewWorkflowResponse,
} from "./pipelineContracts";
import { jsonHeaders, requestJson } from "./transport";

export function createFrameReviewClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<
  DokoDetectorClient,
  "getFrameReviewPage" | "updateFrameReviewWorkflow"
> {
  return {
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
  };
}
