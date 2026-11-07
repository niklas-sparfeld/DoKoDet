import { describe, expect, it, vi } from "vitest";
import { createJobsClient } from "../api/jobsClient";

describe("shared jobs API client", () => {
  it("bounds list and log requests and supports cursor pagination", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("{}", { status: 200 })),
    );
    const client = createJobsClient(fetcher);
    await client.listJobs({ scope: "history", cursor: "cursor/1", limit: 500 });
    await client.getJobLogs("job/1", { after: 4, limit: 900 });
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/jobs?scope=history&limit=100&cursor=cursor%2F1",
    );
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      "/api/jobs/job%2F1/logs?limit=500&after=4",
    );
  });
});
