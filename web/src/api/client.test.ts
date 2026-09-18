import { describe, expect, it, vi } from "vitest";

import {
  createDokoDetectorClient,
  pipelineComparisonPath,
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
  pipelineReviewFramePath,
  pipelineObservationRunPath,
  pipelineObservationRunRetryPath,
  pipelineObservationRunsPath,
  pipelineReferenceCompletionPath,
  pipelineReferenceDraftPath,
  pipelineReferencePath,
  pipelineVisibleCardResultPath,
  pipelineVisualIdentityResultPath,
  pipelineVisualIdentityAutoApprovalPath,
  pipelineVisualIdentityAutoApprovalPlanPath,
  recordingAnalysisPath,
  recordingDetailPath,
  recordingPipelineSelectionPath,
  recordingPipelineWorkspacePath,
  repositoryBundleThumbnailPath,
  repositoryBundleVideoPath,
  roundAnalysisFramePath,
  roundCounterfactualPath,
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
      "/api/recordings/recording%2F1/pipeline/derived-views/exact-event/123456",
    );
    expect(
      pipelineIdentityCropPath("recording/1", "revision/1", "card 1"),
    ).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/identity-crops/revision%2F1/card%201?preview=browser",
    );
  });

  it("plans and applies guarded visual identity auto-approval", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({})),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.planVisualIdentityAutoApproval("recording/1");
    await client.applyVisualIdentityAutoApproval("recording/1", {
      expected_revision: 4,
      operator_id: "operator-1",
      command_id: "command-1",
    });

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineVisualIdentityAutoApprovalPlanPath("recording/1"),
      pipelineVisualIdentityAutoApprovalPath("recording/1"),
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[1]?.[1]?.body).toContain(
      "expected_revision",
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
      table_observation_revision_id: "observations-1",
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
    await client.getObservationRun("recording/1", "observation-run-1");
    await client.retryObservationRun("recording/1", "observation-run-1");
    await client.createRoundAnalysis(analysisPayload);

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineObservationRunsPath("recording/1"),
      pipelineObservationRunPath("recording/1", "observation-run-1"),
      pipelineObservationRunRetryPath("recording/1", "observation-run-1"),
      "/v1/round-analyses",
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[3]?.[1]?.body).toContain(
      "table_observation_revision_id",
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
      selected_generated_revision_id: "events-2",
    });
    await client.comparePipelineRuns("recording/1", comparison);
    await client.getPipelineReference("recording/1", "events");
    await client.createPipelineReference("recording/1", "events", {
      operator_id: "operator-1",
      seed: "selected_generated",
      source_revision_id: "events-1",
    });
    await client.updatePipelineReferenceDraft("recording/1", "events", {
      expected_revision: 2,
      operator_id: "operator-1",
      command_id: "command-1",
      operations: [{ operation: "accept", item_id: "item-1" }],
    });
    await client.completePipelineReference("recording/1", "events", {
      expected_revision: 3,
      operator_id: "reviewer-1",
      coverage: {
        kind: "full_recording",
        intervals: [{ start_us: 0, end_us: 5_000_000 }],
      },
    });

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
    expect(fetchImplementation.mock.calls[3]?.[0]).toBe(
      pipelineReferencePath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[5]?.[0]).toBe(
      pipelineReferenceDraftPath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[6]?.[0]).toBe(
      pipelineReferenceCompletionPath("recording/1", "events"),
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
    await client.createRoundCounterfactual("analysis-1", {
      schema_version: "round-analysis-counterfactual/v1",
      counterfactual_id: "counterfactual-1",
      source_analysis_id: "analysis-1",
      source_input_sha256: "a".repeat(64),
      source_result_sha256: "b".repeat(64),
      excluded_observation_ids: [],
      excluded_observed_cards: [],
      card_identity_overrides: [],
      candidate_probability_overrides: [],
    });
    await client.getRoundCounterfactual("analysis-1", "counterfactual-1");
    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      roundCounterfactualPath("analysis-1"),
      roundCounterfactualReadPath("analysis-1", "counterfactual-1"),
    ]);
  });
});
