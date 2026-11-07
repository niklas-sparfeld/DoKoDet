import { describe, expect, it, vi } from "vitest";

import type { PipelineComparisonRequest } from "./pipelineContracts";
import {
  createPipelineProcessingClient,
  pipelineComparisonPath,
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
  pipelineReviewFramePath,
} from "./pipelineProcessingClient";

describe("pipeline processing client", () => {
  it("keeps result, frame, and comparison URLs stable", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("{}")),
    );
    const client = createPipelineProcessingClient(fetcher);
    const comparison = {
      schema_version: "pipeline-comparison-request/v1",
      recording_id: "recording/1",
      content_type: "events",
      left_run_id: "left",
      right_run_id: "right",
      reference_revision_id: "reference",
      matching_policy: {
        policy_id: "event-timing/v1",
        anchor: "start_us",
        tolerance_us: 50_000,
      },
    } satisfies PipelineComparisonRequest;

    await client.comparePipelineRuns("recording/1", comparison);

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      pipelineComparisonPath("recording/1"),
    );
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify(comparison),
    });
    expect(pipelineDerivedFramePath("recording/1", 123456)).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/exact-event/123456",
    );
    expect(pipelineReviewFramePath("recording/1", 123456)).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/exact-event/250000?preview=sampled_250ms",
    );
    expect(
      pipelineIdentityCropPath("recording/1", "revision/1", "card 1"),
    ).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/identity-crops/revision%2F1/card%201?preview=browser",
    );
  });
});
