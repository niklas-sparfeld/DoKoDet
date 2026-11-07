import { createJobsClient } from "../api/jobsClient";
import { createPipelineProcessingClient } from "../api/pipelineProcessingClient";

export function usePipelineLaunchClient() {
  return { ...createJobsClient(), ...createPipelineProcessingClient() };
}
