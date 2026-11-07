import { describe, expect, it, vi } from "vitest";

import type { RoundAnalysisCreateRequest } from "./analysisContracts";
import {
  createAnalysisClient,
  roundAnalysisFramePath,
  roundCounterfactualReadPath,
} from "./analysisClient";

describe("analysis client", () => {
  it("creates analyses and preserves encoded evidence paths", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("{}")),
    );
    const client = createAnalysisClient(fetcher);
    const payload = {
      analysis_id: "analysis-1",
      recording_id: "recording-1",
      round_id: "round-1",
      session_id: "session-1",
      schema_version: "round-analysis/v1",
      table_observation_node_ref: {
        node_id: "node-1",
        revision_id: "revision-1",
      },
      round_context: {
        game_id: "game-1",
        round_id: "round-1",
        active_players: ["seat-1", "seat-2", "seat-3", "seat-4"],
        dealer: "seat-1",
        first_trick_leader: "seat-1",
      },
      rules_version: "v1",
      search: {
        max_missing_plays: 1,
        max_hypotheses: 256,
        max_search_nodes: 250000,
      },
    } satisfies RoundAnalysisCreateRequest;

    await client.createRoundAnalysis(payload);

    expect(fetcher.mock.calls[0]?.[0]).toBe("/v1/round-analyses");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify(payload),
    });
    expect(roundAnalysisFramePath("analysis/1", "package/2", "frame 03")).toBe(
      "/v1/round-analyses/analysis%2F1/evidence-packages/package%2F2/frames/frame%2003",
    );
    expect(roundCounterfactualReadPath("analysis-1", "counterfactual/1")).toBe(
      "/v1/round-analyses/analysis-1/counterfactuals/counterfactual%2F1",
    );
  });
});
