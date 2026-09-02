import { render, screen } from "@testing-library/react";

import type { CardEventReviewResource } from "../api/client";
import { emptyRecordingDetail } from "../test/roundAnalysisFixture";
import { CardEventReviewPage } from "./CardEventReviewPage";

const review = {
  annotation: {
    schema_version: "cardevent-annotation/v2",
    video: "recording-detail-1.mov",
    events: [{ time_s: 1.25, type: "card_played", confidence: "confirmed" }],
  },
  completed_at: "2026-09-02T14:45:00Z",
  completed_version_digest: "d".repeat(64),
  completed_version_id: "cardevent-reviewed-version-1",
  completion_receipt_id: "receipt-cardevent-review-1",
  draft_digest: "a".repeat(64),
  draft_revision: 2,
  events: [
    {
      event_id: "cardevent-event-1",
      effective_time_s: 1.25,
      type: "card_played",
      confidence: "confirmed",
      notes: null,
      state: "reviewed",
      origin: "manual",
      proposal: null,
    },
    {
      event_id: "cardevent-event-2",
      effective_time_s: 3,
      type: "card_played",
      confidence: "proposed",
      notes: null,
      state: "dismissed",
      origin: "model",
      proposal: {
        proposal_id: "proposal-1",
        proposal_generator_run_id: "run-1",
        proposal_time_s: 3,
        probability: 0.8,
        model_bundle_id: "model-1",
        execution_platform: "local",
      },
    },
  ],
  full_video_acknowledged: true,
  operator: "Niklas",
  parent_digest: "p".repeat(64),
  parent_review_id: "cardevent-review-parent",
  parent_version_id: "cardevent-reviewed-parent",
  proposals: [],
  proposal_decision_digest: "e".repeat(64),
  recording_id: emptyRecordingDetail.recording_id,
  reviewed_annotation_digest: "c".repeat(64),
  reviewer: "Niklas",
  review_id: "cardevent-review-1",
  review_state: "completed",
  review_url: "/card-event-reviews/cardevent-review-1",
  schema_version: "cardevent-review-resource/v1",
  source_asset_id: emptyRecordingDetail.source_asset_id,
  source_sha256: emptyRecordingDetail.source_sha256,
  updated_at: "2026-09-02T14:45:00Z",
  created_at: "2026-09-02T14:32:00Z",
  video: "recording-detail-1.mov",
} satisfies CardEventReviewResource;

describe("CardEventReviewPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads a stable review resource with the recording context and read-only history", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).includes("/card-event-reviews/")
              ? review
              : emptyRecordingDetail,
          ),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<CardEventReviewPage reviewId={review.review_id} />);

    expect(
      await screen.findByRole("heading", { name: "CardEvent review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "This completed review is read-only. Its annotation and lineage are immutable.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("2 events")).toHaveLength(2);
    const eventCounts = screen.getByLabelText("Event counts");
    expect(eventCounts).toHaveTextContent("Reviewed");
    expect(eventCounts).toHaveTextContent("Dismissed");
    expect(screen.getByText("proposal-1")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Source recording recording-detail-1"),
    ).toHaveAttribute("src", emptyRecordingDetail.video.url);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/v1/card-event-reviews/cardevent-review-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/v1/recordings/recording-detail-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
