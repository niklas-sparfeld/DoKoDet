import type { DokoDetectorClient } from "./clientTypes";
import type {
  RecordingDetail,
  RecordingListResponse,
} from "./recordingContracts";

import { requestJson } from "./transport";

export function createRecordingsClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<DokoDetectorClient, "listRecordings" | "getRecording"> {
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
  };
}
export function recordingDetailPath(recordingId: string): string {
  return `/v1/recordings/${encodeURIComponent(recordingId)}`;
}

export function repositoryBundleVideoPath(recordingId: string): string {
  return `/v1/repository-bundles/${encodeURIComponent(recordingId)}/video`;
}

export function repositoryBundleThumbnailPath(recordingId: string): string {
  return `/v1/repository-bundles/${encodeURIComponent(recordingId)}/thumbnail`;
}

function recordingsPath(): string {
  return "/v1/recordings";
}
