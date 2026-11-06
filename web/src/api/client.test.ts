import { describe, expect, it, vi } from "vitest";

import {
  createDokoDetectorClient,
  pipelineComparisonPath,
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
  pipelineReviewFramePath,
  pipelineObservationRunsPath,
  pipelineProposedCardSceneResultPath,
  pipelineProposedCardSceneRunsPath,
  pipelineVisibleCardResultPath,
  pipelineVisualIdentityResultPath,
  recordingAnalysisPath,
  recordingDetailPath,
  recordingPipelineSelectionPath,
  recordingPipelineWorkspacePath,
  repositoryBundleThumbnailPath,
  repositoryBundleVideoPath,
  roundAnalysisFramePath,
  roundCounterfactualReadPath,
  type PipelineComparisonRequest,
  type RoundAnalysisCreateRequest,
} from "./client";

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("DokoDetector API client", () => {
  it("lists recordings and starts reconstruction through recording routes", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({ recordings: [] })),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.listRecordings();
    await client.getRecording("recording/1");
    await client.startRecordingAnalysis("recording/1");

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      "/v1/recordings",
      recordingDetailPath("recording/1"),
      recordingAnalysisPath("recording/1"),
    ]);
    expect(fetchImplementation.mock.calls[2]?.[1]?.method).toBe("POST");
  });

  it("loads pipeline results and recording-owned derived views", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({})),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.getVisibleCardResult("recording/1", "visible/run");
    await client.getVisualIdentityResult("recording/1", "identity/run");

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineVisibleCardResultPath("recording/1", "visible/run"),
      pipelineVisualIdentityResultPath("recording/1", "identity/run"),
    ]);
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

  it("starts, lists, and reads proposed card-scene results", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({ status: "complete", state: {} })),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.startProposedCardSceneRun("recording/1", {
      run_id: "proposal/run",
      visible_card_revision_id: "visible-revision-1",
    });
    await client.listProposedCardSceneRuns("recording/1");
    await client.getProposedCardSceneResult("recording/1", "proposal/run");

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineProposedCardSceneRunsPath("recording/1"),
      pipelineProposedCardSceneRunsPath("recording/1"),
      pipelineProposedCardSceneResultPath("recording/1", "proposal/run"),
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[0]?.[1]?.body).toContain(
      "visible_card_revision_id",
    );
  });

  it("runs observation assembly and explicit round analysis", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({})),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    const runPayload = {
      request: {
        run_id: "observation-run-1",
        input_revision_ids: ["events-1", "visible-1", "identity-1"],
      },
    };
    const analysisPayload = {
      analysis_id: "550e8400-e29b-41d4-a716-446655440033",
      recording_id: "recording-1",
      round_id: "round-1",
      session_id: "550e8400-e29b-41d4-a716-446655440034",
      schema_version: "round-analysis/v1",
      table_observation_node_ref: {
        node_id: "observations-node-1",
        revision_id: "observations-node-revision-1",
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

    await client.startObservationRun("recording/1", runPayload);
    await client.createRoundAnalysis(analysisPayload);

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineObservationRunsPath("recording/1"),
      "/v1/round-analyses",
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[1]?.[1]?.body).toContain(
      "table_observation_node_ref",
    );
  });

  it("runs comparisons and maintains references through pipeline paths", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({})),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    const comparison = {
      schema_version: "pipeline-comparison-request/v1",
      recording_id: "recording/1",
      content_type: "events",
      left_run_id: "run-left",
      right_run_id: "run-right",
      reference_revision_id: "reference-1",
      matching_policy: {
        policy_id: "event-timing/v1",
        anchor: "start_us",
        tolerance_us: 50_000,
      },
    } satisfies PipelineComparisonRequest;

    await client.getRecordingPipeline("recording/1");
    await client.updatePipelineSelection("recording/1", "events", {
      expected_revision: 4,
      selected_generated: {
        node_id: "events-node",
        revision_id: "events-node-r2",
      },
    });
    await client.comparePipelineRuns("recording/1", comparison);
    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      recordingPipelineWorkspacePath("recording/1"),
    );
    expect(
      recordingPipelineWorkspacePath("recording/1", "visual_identities"),
    ).toBe("/api/recordings/recording%2F1/pipeline?stage=visual_identities");
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(
      recordingPipelineSelectionPath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[2]?.[0]).toBe(
      pipelineComparisonPath("recording/1"),
    );
  });

  it("raises an API error with the response body", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response('{"code":"missing"}', { status: 404 }));
    const client = createDokoDetectorClient(fetchImplementation);

    await expect(
      client.getRoundAnalysisStatus("missing"),
    ).rejects.toMatchObject({
      status: 404,
      body: { code: "missing" },
    });
  });

  it("encodes source and counterfactual paths", async () => {
    expect(repositoryBundleVideoPath("recording/1")).toBe(
      "/v1/repository-bundles/recording%2F1/video",
    );
    expect(repositoryBundleThumbnailPath("recording/1")).toBe(
      "/v1/repository-bundles/recording%2F1/thumbnail",
    );
    expect(roundAnalysisFramePath("analysis/1", "package/2", "frame 03")).toBe(
      "/v1/round-analyses/analysis%2F1/evidence-packages/package%2F2/frames/frame%2003",
    );

    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({})),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    await client.getRoundCounterfactual("analysis-1", "counterfactual-1");
    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      roundCounterfactualReadPath("analysis-1", "counterfactual-1"),
    ]);
  });
});
