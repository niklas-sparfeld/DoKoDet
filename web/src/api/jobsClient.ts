import type { DokoDetectorClient } from "./clientTypes";
import type { components } from "./openapi";
import type { CalibrationRefinementResponse } from "./calibrationContracts";
import type { JobDetail, JobListResponse, JobLogPage } from "./jobsContracts";

import { jsonHeaders, requestJson } from "./transport";

export function createJobsClient(
  fetchImplementation: typeof fetch = fetch,
): Pick<
  DokoDetectorClient,
  | "listJobs"
  | "getJobLogs"
  | "cancelJob"
  | "enqueueJob"
  | "getJob"
  | "getCalibrationPreview"
  | "retryJob"
  | "moveJob"
> {
  return {
    listJobs: (options = {}) => {
      const query = new URLSearchParams();
      query.set("scope", options.scope ?? "active");
      query.set(
        "limit",
        String(Math.min(100, Math.max(1, options.limit ?? 50))),
      );
      if (options.cursor) query.set("cursor", options.cursor);
      return requestJson<JobListResponse>(
        fetchImplementation,
        `/api/jobs?${query}`,
        { signal: options.signal },
      );
    },
    getJobLogs: (jobId, options = {}) => {
      const query = new URLSearchParams();
      query.set(
        "limit",
        String(Math.min(500, Math.max(1, options.limit ?? 100))),
      );
      if (options.after !== undefined)
        query.set("after", String(Math.max(0, options.after)));
      return requestJson<JobLogPage>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/logs?${query}`,
        { signal: options.signal },
      );
    },
    cancelJob: (jobId, init) =>
      requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/cancel`,
        {
          ...init,
          method: "POST",
          headers: jsonHeaders(init?.headers),
          body: JSON.stringify({}),
        },
      ),
    enqueueJob: (payload, idempotencyKey, init) => {
      const headers = jsonHeaders(init?.headers);
      headers.set("Idempotency-Key", idempotencyKey);
      return requestJson<JobDetail>(fetchImplementation, "/api/jobs", {
        ...init,
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
    },
    getJob: (jobId, init) =>
      requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}`,
        init,
      ),
    getCalibrationPreview: (jobId, init) =>
      requestJson<CalibrationRefinementResponse>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/calibration-preview`,
        init,
      ),
    retryJob: (jobId, idempotencyKey, init) => {
      const headers = jsonHeaders(init?.headers);
      headers.set("Idempotency-Key", idempotencyKey);
      return requestJson<JobDetail>(
        fetchImplementation,
        `/api/jobs/${encodeURIComponent(jobId)}/retry`,
        { ...init, method: "POST", headers, body: JSON.stringify({}) },
      );
    },
    moveJob: (groupId, beforeGroupId, expectedRevision) =>
      requestJson<components["schemas"]["QueueMoveResponse"]>(
        fetchImplementation,
        "/api/jobs/queue/move",
        {
          method: "POST",
          headers: jsonHeaders(undefined),
          body: JSON.stringify({
            group_id: groupId,
            before_group_id: beforeGroupId,
            expected_revision: expectedRevision,
          }),
        },
      ),
  };
}
