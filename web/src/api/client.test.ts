import { describe, expect, it, vi } from "vitest";

import {
  createDokoDetectorClient,
  cardEventReviewEventPath,
  cardEventReviewEventsPath,
  cardEventReviewResourceCompletionPath,
  cardEventReviewResourcePath,
  recordingAnalysisPath,
  recordingCardEventReviewsPath,
  recordingCardEventReviewCompletionPath,
  recordingCardEventReviewDraftPath,
  recordingCardEventReviewPath,
  recordingCardEventReviewRevisionPath,
  recordingDetailPath,
  recordingPipelineWorkspacePath,
  recordingPipelineSelectionPath,
  pipelineEventResultPath,
  pipelineVisibleCardResultPath,
  pipelineVisualIdentityResultPath,
  pipelineObservationRunPath,
  pipelineObservationRunRetryPath,
  pipelineObservationRunsPath,
  pipelineIdentityCropPath,
  pipelineDerivedFramePath,
  pipelineReferencePath,
  pipelineReferenceDraftPath,
  pipelineReferenceCompletionPath,
  repositoryBundleVideoPath,
  roundAnalysisFramePath,
  roundCounterfactualPath,
  roundCounterfactualReadPath,
  type RoundAnalysisCreateRequest,
  identityReviewPreviewPath,
  visibleCardReviewItemRedetectPath,
} from "./client";

describe("DokoDetector API client", () => {
  it("lists recordings and starts a recording analysis", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({ recordings: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.listRecordings();
    expect(fetchImplementation.mock.calls[0]?.[0]).toBe("/v1/recordings");
    expect(
      new Headers(fetchImplementation.mock.calls[0]?.[1]?.headers).get(
        "Accept",
      ),
    ).toBe("application/json");

    await client.getRecording("recording/1");
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(
      recordingDetailPath("recording/1"),
    );

    await client.startRecordingAnalysis("recording/1");
    expect(fetchImplementation.mock.calls[2]?.[0]).toBe(
      recordingAnalysisPath("recording/1"),
    );
    expect(fetchImplementation.mock.calls[2]?.[1]?.method).toBe("POST");
  });

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

  it("loads visible-card results and recording-owned derived frames", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.getVisibleCardResult("recording/1", "visible/run");
    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      pipelineVisibleCardResultPath("recording/1", "visible/run"),
    );
    expect(pipelineDerivedFramePath("recording/1", 123456)).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/exact-event/123456",
    );
  });

  it("runs observation assembly and explicit round analysis through typed paths", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    const runPayload = {
      request: {
        run_id: "observation-run-1",
        input_revision_ids: ["events-1", "visible-1", "identity-1"],
      },
    };
    await client.startObservationRun("recording/1", runPayload);
    await client.getObservationRun("recording/1", "observation-run-1");
    await client.retryObservationRun("recording/1", "observation-run-1");
    await client.createRoundAnalysis({
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
    } satisfies RoundAnalysisCreateRequest);

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      pipelineObservationRunsPath("recording/1"),
      pipelineObservationRunPath("recording/1", "observation-run-1"),
      pipelineObservationRunRetryPath("recording/1", "observation-run-1"),
      "/v1/round-analyses",
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[2]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[3]?.[1]?.body).toContain(
      "table_observation_revision_id",
    );
  });

  it("loads identity results and recording-owned identity crops", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.getVisualIdentityResult("recording/1", "identity/run");
    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      pipelineVisualIdentityResultPath("recording/1", "identity/run"),
    );
    expect(
      pipelineIdentityCropPath("recording/1", "revision/1", "card 1"),
    ).toBe(
      "/api/recordings/recording%2F1/pipeline/derived-views/identity-crops/revision%2F1/card%201",
    );
  });

  it("reads and writes the recording-scoped CardEvent review through generated paths", async () => {
    const response = {
      annotation: {
        schema_version: "cardevent-annotation/v2",
        video: "video.mov",
        events: [],
      },
      completed_at: null,
      completed_version_digest: null,
      completed_version_id: null,
      completion_receipt_id: null,
      draft_digest: "a".repeat(64),
      draft_revision: 0,
      full_video_acknowledged: false,
      parent_digest: null,
      parent_version_id: null,
      proposals: [],
      proposal_decision_digest: null,
      recording_id: "recording-1",
      reviewed_annotation_digest: null,
      review_state: "not_started",
      reviewer: null,
      schema_version: "cardevent-review/v1",
      source_asset_id: "source-1",
      source_sha256: "b".repeat(64),
      video: "video.mov",
    } as const;
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);
    const draft = {
      annotation: response.annotation,
      proposals: [],
      expected_revision: 0,
      full_video_acknowledged: false,
    };

    await client.getCardEventReview("recording/1");
    await client.updateCardEventReviewDraft("recording/1", draft);
    await client.completeCardEventReview("recording/1", {
      reviewer: "operator",
      expected_revision: 0,
      full_video_acknowledged: true,
    });
    await client.startCardEventReviewRevision("recording/1", {
      parent_version_id: "version-1",
      expected_revision: 0,
    });

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      recordingCardEventReviewPath("recording/1"),
      recordingCardEventReviewDraftPath("recording/1"),
      recordingCardEventReviewCompletionPath("recording/1"),
      recordingCardEventReviewRevisionPath("recording/1"),
    ]);
    expect(fetchImplementation.mock.calls[1]?.[1]?.method).toBe("PUT");
    expect(fetchImplementation.mock.calls[2]?.[1]?.method).toBe("POST");
    expect(
      new Headers(fetchImplementation.mock.calls[1]?.[1]?.headers).get(
        "Content-Type",
      ),
    ).toBe("application/json");
  });

  it("creates and completes a recording-owned CardEvent review resource", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    const created = await client.createCardEventReview("recording/1", {
      operator: "operator",
    });
    const reviewId = "cardevent-review-00000000000000000000000000000000";
    await client.listCardEventReviews("recording/1");
    await client.getCardEventReviewResource(reviewId);
    await client.updateCardEventReviewResource(reviewId, {
      annotation: {
        schema_version: "cardevent-annotation/v2",
        video: "video.mov",
        events: [],
      },
      proposals: [],
      expected_revision: 0,
      full_video_acknowledged: false,
    });
    await client.completeCardEventReviewResource(reviewId, {
      reviewer: "operator",
      expected_revision: 0,
      full_video_acknowledged: true,
    });

    expect(created).toEqual({});
    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      recordingCardEventReviewsPath("recording/1"),
      recordingCardEventReviewsPath("recording/1"),
      cardEventReviewResourcePath(reviewId),
      cardEventReviewResourcePath(reviewId),
      cardEventReviewResourceCompletionPath(reviewId),
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[3]?.[1]?.method).toBe("PUT");
    expect(fetchImplementation.mock.calls[4]?.[1]?.method).toBe("POST");
  });

  it("sends unified CardEvent commands through generated resource paths", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.addCardEvent("review/1", {
      client_command_id: "command-1",
      expected_revision: 0,
      effective_time_s: 1.2,
      type: "card_played",
      confidence: "confirmed",
    });
    await client.updateCardEvent("review/1", "event/1", {
      client_command_id: "command-2",
      expected_revision: 1,
      action: "accept",
    });

    expect(fetchImplementation.mock.calls.map(([path]) => path)).toEqual([
      cardEventReviewEventsPath("review/1"),
      cardEventReviewEventPath("review/1", "event/1"),
    ]);
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[1]?.[1]?.method).toBe("PATCH");
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

  it("re-detects one visible-card frame through its item path", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.redetectVisibleCardReviewItem("batch/1", "item:1", {
      expected_revision: 4,
      model: "gemini-3.7-flash",
    });

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      visibleCardReviewItemRedetectPath("batch/1", "item:1"),
    );
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(
      JSON.parse(String(fetchImplementation.mock.calls[0]?.[1]?.body)),
    ).toEqual({
      expected_revision: 4,
      model: "gemini-3.7-flash",
    });
  });

  it("sends the selected identity crop policy in the preview request", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.previewIdentityReview("recording/1", {
      crop_policy_id: "oracle_visible_region",
    });

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      identityReviewPreviewPath("recording/1"),
    );
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(
      JSON.parse(String(fetchImplementation.mock.calls[0]?.[1]?.body)),
    ).toEqual({ crop_policy_id: "oracle_visible_region" });
  });

  it("encodes the complete recording path", () => {
    expect(repositoryBundleVideoPath("recording/1")).toBe(
      "/v1/repository-bundles/recording%2F1/video",
    );
    expect(recordingDetailPath("recording/1")).toBe(
      "/v1/recordings/recording%2F1",
    );
  });

  it("loads the recording-owned pipeline workspace", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.getRecordingPipeline("recording/1");

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      recordingPipelineWorkspacePath("recording/1"),
    );
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBeUndefined();
  });

  it("updates a recording-owned pipeline selection with its expected revision", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            recording_id: "recording-1",
            selection: {
              revision: 5,
              recording_id: "recording-1",
              content_type: "events",
              selected_generated_revision_id: "events-2",
              selected_completed_reference_revision_id: null,
              updated_at: "2026-09-06T00:00:00Z",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.updatePipelineSelection("recording/1", "events", {
      expected_revision: 4,
      selected_generated_revision_id: "events-2",
    });

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      recordingPipelineSelectionPath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[0]?.[1]?.method).toBe("PUT");
    expect(
      JSON.parse(String(fetchImplementation.mock.calls[0]?.[1]?.body)),
    ).toEqual({
      expected_revision: 4,
      selected_generated_revision_id: "events-2",
    });
  });

  it("reads and updates the recording-owned event reference", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = createDokoDetectorClient(fetchImplementation);

    await client.getEventResult("recording/1", "run/1");
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
      pipelineEventResultPath("recording/1", "run/1"),
    );
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(
      pipelineReferencePath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[2]?.[0]).toBe(
      pipelineReferencePath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[2]?.[1]?.method).toBe("POST");
    expect(fetchImplementation.mock.calls[3]?.[0]).toBe(
      pipelineReferenceDraftPath("recording/1", "events"),
    );
    expect(
      JSON.parse(String(fetchImplementation.mock.calls[3]?.[1]?.body)),
    ).toEqual({
      expected_revision: 2,
      operator_id: "operator-1",
      command_id: "command-1",
      operations: [{ operation: "accept", item_id: "item-1" }],
    });
    expect(fetchImplementation.mock.calls[4]?.[0]).toBe(
      pipelineReferenceCompletionPath("recording/1", "events"),
    );
    expect(fetchImplementation.mock.calls[4]?.[1]?.method).toBe("POST");
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
