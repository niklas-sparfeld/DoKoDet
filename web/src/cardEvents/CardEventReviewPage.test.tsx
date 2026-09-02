import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("loads a stable review resource with the recording context and revision entry point", async () => {
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
        "This completed version is read-only to preserve its lineage. Start a revision below to edit or remove events; the recording remains unchanged.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Correct annotations" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("2 events")).toHaveLength(3);
    const eventCounts = screen.getByLabelText("Event counts");
    expect(eventCounts).toHaveTextContent("Reviewed");
    expect(eventCounts).toHaveTextContent("Dismissed");
    expect(screen.getByText("proposal-1")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Source recording recording-detail-1"),
    ).toHaveAttribute("src", emptyRecordingDetail.video.url);
    expect(screen.getByLabelText("Event navigator")).toHaveTextContent(
      "Current event",
    );
    expect(screen.getByLabelText("Event navigator")).toHaveTextContent(
      "0:01.250",
    );
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

  it("starts an editable revision from a completed review", async () => {
    const revision = {
      ...review,
      review_id: "cardevent-review-revision-1",
      review_url: "/card-event-reviews/cardevent-review-revision-1",
      review_state: "draft" as const,
      parent_review_id: review.review_id,
      parent_version_id: review.completed_version_id,
      parent_digest: review.completed_version_digest,
      reviewer: null,
      completed_at: null,
      completed_version_id: null,
      completed_version_digest: null,
      completion_receipt_id: null,
      reviewed_annotation_digest: null,
      proposal_decision_digest: null,
      full_video_acknowledged: false,
    } satisfies CardEventReviewResource;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const method = init?.method ?? "GET";
      const url = String(input);
      if (method === "GET" && url.endsWith("/card-event-reviews")) {
        return new Response(
          JSON.stringify({
            schema_version: "cardevent-review-collection/v1",
            recording_id: review.recording_id,
            current_review_id: review.review_id,
            draft_review_id: null,
            latest_completed_review_id: review.review_id,
            reviews: [],
          }),
          { headers: { "Content-Type": "application/json" } },
        );
      }
      if (method === "POST") {
        expect(url).toBe(
          "/v1/recordings/recording-detail-1/card-event-reviews",
        );
        expect(JSON.parse(String(init?.body))).toEqual({
          operator: review.operator,
          parent_review_id: review.review_id,
        });
        return new Response(JSON.stringify(revision), {
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify(
          url.includes("/card-event-reviews/") ? review : emptyRecordingDetail,
        ),
        { headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CardEventReviewPage reviewId={review.review_id} />);
    await screen.findByRole("button", { name: "Correct annotations" });

    fireEvent.click(
      screen.getByRole("button", { name: "Correct annotations" }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(window.location.pathname).toBe(
      "/card-event-reviews/cardevent-review-revision-1",
    );
  });

  it("marks a fully watched draft complete from the bottom action bar", async () => {
    const draft = {
      ...review,
      review_state: "draft" as const,
      reviewer: null,
      completed_at: null,
      completed_version_id: null,
      completed_version_digest: null,
      completion_receipt_id: null,
      reviewed_annotation_digest: null,
      proposal_decision_digest: null,
      full_video_acknowledged: false,
    } satisfies CardEventReviewResource;
    let completionPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/complete")) {
        const payload = JSON.parse(String(init.body)) as Record<
          string,
          unknown
        >;
        completionPayload = payload;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...review,
              reviewer: payload.reviewer,
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify(
            url.includes("/card-event-reviews/") ? draft : emptyRecordingDetail,
          ),
          { headers: { "Content-Type": "application/json" } },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CardEventReviewPage reviewId={draft.review_id} />);

    const video = await screen.findByLabelText(
      "Source recording recording-detail-1",
    );
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 12.5,
    });
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 12.5,
      writable: true,
    });
    fireEvent(video, new Event("loadedmetadata"));
    fireEvent(video, new Event("timeupdate"));

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Reviewer" }), {
      target: { value: "Niklas" },
    });
    const complete = screen.getByRole("button", {
      name: "Mark review complete",
    });
    await waitFor(() => expect(complete).toBeEnabled());
    fireEvent.click(complete);

    await waitFor(() =>
      expect(completionPayload).toMatchObject({
        reviewer: "Niklas",
        expected_revision: draft.draft_revision,
        full_video_acknowledged: true,
      }),
    );
    expect(
      await screen.findByRole("button", { name: "Correct annotations" }),
    ).toBeInTheDocument();
  });

  it("queues keyboard decisions in order while projecting them immediately", async () => {
    const firstEvent = {
      ...review.events[0],
      event_id: "cardevent-event-proposed-1",
      effective_time_s: 1.25,
      confidence: "proposed" as const,
      state: "proposed" as const,
      origin: "model" as const,
      proposal: {
        proposal_id: "proposal-1",
        proposal_generator_run_id: "run-1",
        proposal_time_s: 1.25,
        probability: 0.8,
        model_bundle_id: "model-1",
        execution_platform: "local",
      },
    };
    const secondEvent = {
      ...firstEvent,
      event_id: "cardevent-event-proposed-2",
      effective_time_s: 3,
      proposal: { ...firstEvent.proposal, proposal_id: "proposal-2" },
    };
    let revision = 0;
    const commands: Array<{ action: string; expected_revision: number }> = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const method = init?.method ?? "GET";
      const url = String(input);
      if (method === "GET" && url.includes("/card-event-reviews/")) {
        return new Response(
          JSON.stringify({
            ...review,
            review_state: "draft",
            draft_revision: 0,
            reviewer: null,
            completed_at: null,
            completed_version_id: null,
            completed_version_digest: null,
            completion_receipt_id: null,
            events: [firstEvent, secondEvent],
            proposals: [],
            full_video_acknowledged: false,
          }),
          { headers: { "Content-Type": "application/json" } },
        );
      }
      if (method === "GET") {
        return new Response(JSON.stringify(emptyRecordingDetail), {
          headers: { "Content-Type": "application/json" },
        });
      }
      const payload = JSON.parse(String(init?.body)) as {
        action: string;
        expected_revision: number;
        client_command_id: string;
      };
      commands.push({
        action: payload.action,
        expected_revision: payload.expected_revision,
      });
      revision += 1;
      const eventId = url.includes(secondEvent.event_id)
        ? secondEvent.event_id
        : firstEvent.event_id;
      const sourceEvent =
        eventId === firstEvent.event_id ? firstEvent : secondEvent;
      const changedEvent = {
        ...sourceEvent,
        state: payload.action === "accept" ? "reviewed" : "dismissed",
        confidence: payload.action === "accept" ? "confirmed" : "ignore",
      };
      return new Response(
        JSON.stringify({
          schema_version: "cardevent-review-event/v1",
          review_id: review.review_id,
          draft_revision: revision,
          changed_event: changedEvent,
          event_counts: {
            reviewed: payload.action === "accept" ? 1 : 0,
            proposed: 0,
            dismissed: payload.action === "dismiss" ? 1 : 0,
          },
          completion_blockers: [],
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CardEventReviewPage reviewId={review.review_id} />);
    await screen.findByRole("heading", { name: "Draft review" });

    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(window, { key: "A" });
    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(window, { key: "D" });

    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands).toEqual([
      { action: "accept", expected_revision: 0 },
      { action: "dismiss", expected_revision: 1 },
    ]);
    expect((await screen.findAllByText("Dismissed")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Retrying")).not.toBeInTheDocument();
  });

  it("keeps the selected event visible beside the source video", async () => {
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
    await screen.findByRole("heading", { name: "CardEvent review" });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Open event 1 at 0:01.250",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next marker" }));

    const navigator = screen.getByLabelText("Event navigator");
    expect(navigator).toHaveTextContent("0:03.000");
    expect(
      screen.getByRole("button", { name: "Open event 2 at 0:03.000" }),
    ).toHaveAttribute("aria-current", "true");
  });

  it("makes a selected dismissed event obvious in the source video", async () => {
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
    await screen.findByRole("heading", { name: "CardEvent review" });

    const sourceVideo = screen.getByLabelText(
      "Source recording recording-detail-1",
    );
    expect(sourceVideo.parentElement).not.toHaveAttribute("data-state");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Open event 2 at 0:03.000",
      }),
    );

    expect(sourceVideo.parentElement).toHaveAttribute(
      "data-state",
      "dismissed",
    );
    expect(
      screen.getByRole("status", {
        name: "Dismissed event. Ignore this event.",
      }),
    ).toBeInTheDocument();
  });

  it("keeps selected-event actions above the event table", async () => {
    const draftReview = {
      ...review,
      review_state: "draft" as const,
      completed_at: null,
      completed_version_id: null,
      completed_version_digest: null,
      completion_receipt_id: null,
      full_video_acknowledged: false,
    } satisfies CardEventReviewResource;
    const fetchMock = vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).includes("/card-event-reviews/")
              ? draftReview
              : emptyRecordingDetail,
          ),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<CardEventReviewPage reviewId={review.review_id} />);
    await screen.findByRole("heading", { name: "Draft review" });

    const actions = screen.getByLabelText("Selected event actions");
    expect(screen.getByLabelText("Event navigator")).toContainElement(actions);
    expect(
      within(actions).getByRole("button", { name: /^Nudge \+1 frame/ }),
    ).toBeEnabled();
    const table = screen.getByRole("table", {
      name: "Unified time-ordered CardEvent review events",
    });
    expect(actions.compareDocumentPosition(table)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("shows the selected event fields in the video-side navigator", async () => {
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
    await screen.findByRole("heading", { name: "CardEvent review" });

    expect(screen.getByLabelText("Time in event navigator")).toHaveValue(1.25);
    expect(screen.getByLabelText("Event type in event navigator")).toHaveValue(
      "card_played",
    );
    expect(screen.getByLabelText("Time in event navigator")).toBeDisabled();
  });

  it("renders an event-time screenshot in every review row", async () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(
      "data:image/jpeg;base64,event-frame",
    );
    Object.defineProperty(HTMLMediaElement.prototype, "readyState", {
      configurable: true,
      get: () => HTMLMediaElement.HAVE_CURRENT_DATA,
    });
    Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", {
      configurable: true,
      get: () => 1920,
    });
    Object.defineProperty(HTMLVideoElement.prototype, "videoHeight", {
      configurable: true,
      get: () => 1080,
    });
    let currentTime = 0;
    Object.defineProperty(HTMLVideoElement.prototype, "currentTime", {
      configurable: true,
      get: () => currentTime,
      set: function (this: HTMLVideoElement, value: number) {
        currentTime = value;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("seeked"));
        });
      },
    });
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

    const screenshots = await screen.findAllByRole("img", {
      name: /Screenshot at/,
    });
    expect(screenshots).toHaveLength(review.events.length);
    expect(screenshots[0]).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,event-frame",
    );
    expect(drawImage).toHaveBeenCalledTimes(review.events.length);
  });
});
