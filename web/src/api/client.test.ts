import { describe, expect, it, vi } from "vitest";

import {
  createDokoDetectorClient,
  recordingAnalysisPath,
  recordingCardEventReviewCompletionPath,
  recordingCardEventReviewDraftPath,
  recordingCardEventReviewPath,
  recordingCardEventReviewRevisionPath,
  recordingDetailPath,
  repositoryBundleVideoPath,
  roundAnalysisFramePath,
  roundCounterfactualPath,
  roundCounterfactualReadPath,
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

  it("encodes the complete recording path", () => {
    expect(repositoryBundleVideoPath("recording/1")).toBe(
      "/v1/repository-bundles/recording%2F1/video",
    );
    expect(recordingDetailPath("recording/1")).toBe(
      "/v1/recordings/recording%2F1",
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
