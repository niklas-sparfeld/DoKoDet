import { describe, expect, it } from "vitest";
import { validatedJobResultHref } from "./JobComponents";
import type { JobDetail } from "../api/client";

const job = { id: "job-1", context: {} } as JobDetail;

describe("validatedJobResultHref", () => {
  it("accepts an exact result path for this job", () => {
    expect(
      validatedJobResultHref(job, {
        path: "/api/jobs/job-1/calibration-preview",
      }),
    ).toBe("/api/jobs/job-1/calibration-preview");
  });
  it("rejects external, unrelated, and incomplete result paths", () => {
    expect(
      validatedJobResultHref(job, {
        path: "https://example.com/api/jobs/job-1/result",
      }),
    ).toBeNull();
    expect(
      validatedJobResultHref(job, { path: "/api/jobs/job-2/result" }),
    ).toBeNull();
    expect(
      validatedJobResultHref(job, { path: "/api/jobs/job-1/../job-2" }),
    ).toBeNull();
  });
  it("accepts a counterfactual only when both immutable identifiers match", () => {
    const counterfactualJob = {
      ...job,
      context: { analysis_id: "analysis-1" },
    } as JobDetail;
    expect(
      validatedJobResultHref(counterfactualJob, {
        id: "result-1",
        path: "/v1/round-analyses/analysis-1/counterfactuals/result-1",
      }),
    ).not.toBeNull();
    expect(
      validatedJobResultHref(counterfactualJob, {
        id: "result-2",
        path: "/v1/round-analyses/analysis-1/counterfactuals/result-1",
      }),
    ).toBeNull();
  });
});
