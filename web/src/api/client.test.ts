import { describe, expect, it, vi } from "vitest";

import {
  createDokoDetectorClient,
  roundAnalysisFramePath,
  roundCounterfactualPath,
  roundCounterfactualReadPath,
} from "./client";

describe("DokoDetector API client", () => {
  it("uses generated timeline types at the API boundary", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          analysis_id: "analysis-1",
          artifact_hashes: {},
          diagnostics: {},
          focused_decisions: [],
          hypotheses: [],
          inferred_plays: [],
          reconstruction_status: "resolved",
          recording_id: "recording-1",
          round_id: "round-1",
          rows: [],
          schema_version: "round-analysis-timeline/v1",
          search: {},
          session_id: "session-1",
          warnings: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    const timeline = await client.getRoundAnalysisTimeline("analysis/1");

    expect(timeline.reconstruction_status).toBe("resolved");
    const [path, requestInit] = fetchImplementation.mock.calls[0];
    expect(path).toBe("/v1/round-analyses/analysis%2F1/timeline");
    expect(new Headers(requestInit?.headers).get("Accept")).toBe(
      "application/json",
    );
  });

  it("raises an API error with the response body", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response('{"code":"analysis_not_found"}', { status: 404 }),
      );
    const client = createDokoDetectorClient(fetchImplementation);

    await expect(
      client.getRoundAnalysisStatus("missing"),
    ).rejects.toMatchObject({
      status: 404,
      body: { code: "analysis_not_found" },
    });
  });

  it("encodes every frame path segment", () => {
    expect(roundAnalysisFramePath("analysis/1", "package/2", "frame 03")).toBe(
      "/v1/round-analyses/analysis%2F1/evidence-packages/package%2F2/frames/frame%2003",
    );
  });

  it("creates and reads a counterfactual through the generated API paths", async () => {
    const response = {
      counterfactual_id: "counterfactual-1",
      source_analysis_id: "analysis-1",
      request: {},
      artifacts: {},
      result: {},
      schema_version: "round-analysis-counterfactual-response/v1",
    };
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    const payload = {
      schema_version: "round-analysis-counterfactual/v1" as const,
      counterfactual_id: "counterfactual-1",
      source_analysis_id: "analysis-1",
      source_input_sha256: "a".repeat(64),
      source_result_sha256: "b".repeat(64),
      excluded_observation_ids: ["observation-1"],
      excluded_observed_cards: [],
      card_identity_overrides: [],
      candidate_probability_overrides: [],
    };

    await client.createRoundCounterfactual("analysis-1", payload);
    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      roundCounterfactualPath("analysis-1"),
    );
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(
      new Headers(fetchImplementation.mock.calls[0]?.[1]?.headers).get(
        "Content-Type",
      ),
    ).toBe("application/json");
    expect(
      JSON.parse(String(fetchImplementation.mock.calls[0]?.[1]?.body)),
    ).toEqual(payload);

    await client.getRoundCounterfactual("analysis-1", "counterfactual-1");
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(
      roundCounterfactualReadPath("analysis-1", "counterfactual-1"),
    );
  });
});
