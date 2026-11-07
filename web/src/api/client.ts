import { createAnalysisClient } from "./analysisClient";
import { createCalibrationClient } from "./calibrationClient";
import { createFrameReviewClient } from "./frameReviewClient";
import { createJobsClient } from "./jobsClient";
import { createPipelineProcessingClient } from "./pipelineProcessingClient";
import { createRecordingsClient } from "./recordingsClient";

export function createDokoDetectorClient(
  fetchImplementation: typeof fetch = fetch,
) {
  return {
    ...createJobsClient(fetchImplementation),
    ...createFrameReviewClient(fetchImplementation),
    ...createRecordingsClient(fetchImplementation),
    ...createPipelineProcessingClient(fetchImplementation),
    ...createCalibrationClient(fetchImplementation),
    ...createAnalysisClient(fetchImplementation),
  };
}

export type DokoDetectorClient = ReturnType<typeof createDokoDetectorClient>;
