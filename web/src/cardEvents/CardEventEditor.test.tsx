import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import type { CardEventReview } from "../api/client";
import { emptyRecordingDetail } from "../test/roundAnalysisFixture";
import { CardEventEditor } from "./CardEventEditor";

const recordingId = "recording-card-events";
type ProposalDecision = "undecided" | "accepted" | "dismissed";
const proposalOne = {
  proposal_id: "proposal-one",
  proposal_generator_run_id: "run-one",
  time_s: 1.5,
  probability: 0.91,
  model_bundle_id: "model-one",
  execution_platform: "local",
  decision: "undecided" as const,
};
const proposalTwo = {
  proposal_id: "proposal-two",
  proposal_generator_run_id: "run-two",
  time_s: 3,
  probability: 0.72,
  model_bundle_id: "model-two",
  execution_platform: "local",
  decision: "undecided" as const,
};

function reviewResponse(
  events: Array<Record<string, unknown>> = [],
  proposals: CardEventReview["proposals"] = [proposalOne, proposalTwo],
  revision = 0,
  overrides: Partial<CardEventReview> = {},
): CardEventReview {
  return {
    annotation: {
      schema_version: "cardevent-annotation/v2",
      video: "card-events.mov",
      events,
    },
    completed_at: null,
    completed_version_digest: null,
    completed_version_id: null,
    completion_receipt_id: null,
    draft_digest: "a".repeat(64),
    draft_revision: revision,
    full_video_acknowledged: false,
    parent_digest: null,
    parent_version_id: null,
    proposals,
    proposal_decision_digest: null,
    recording_id: recordingId,
    reviewed_annotation_digest: null,
    review_state: revision === 0 ? "not_started" : "draft",
    reviewer: null,
    schema_version: "cardevent-review/v1",
    source_asset_id: "source-card-events",
    source_sha256: "b".repeat(64),
    video: "card-events.mov",
    ...overrides,
  };
}

function renderEditor(
  fetchImplementation: typeof fetch,
  summary: typeof emptyRecordingDetail.card_event_review = emptyRecordingDetail.card_event_review,
) {
  vi.stubGlobal("fetch", fetchImplementation);
  return render(
    <CardEventEditor
      recordingId={recordingId}
      videoUrl="/v1/repository-bundles/recording-card-events/video"
      mediaFacts={emptyRecordingDetail.video.media_facts}
      summary={summary}
    />,
  );
}

function response(value: CardEventReview, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("CardEventEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists manual add, frame retime, field edits, and removal", async () => {
    let revision = 0;
    const savedBodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (init?.method !== "PUT") {
        return Promise.resolve(response(reviewResponse()));
      }
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      savedBodies.push(body);
      revision += 1;
      return Promise.resolve(
        response(
          reviewResponse(
            (body.annotation as { events: Array<Record<string, unknown>> })
              .events,
            [proposalOne, proposalTwo],
            revision,
          ),
        ),
      );
    });
    renderEditor(fetchMock);

    const video = await screen.findByLabelText(
      "CardEvent source video recording-card-events",
    );
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 2,
      writable: true,
    });
    fireEvent(video, new Event("timeupdate"));
    await screen.findByText(/Playhead 0:02\.000/);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Add event at playhead" }));

    await waitFor(() => expect(savedBodies).toHaveLength(1));
    expect(savedBodies[0]?.annotation).toMatchObject({
      events: [{ time_s: 2, type: "card_played", confidence: "confirmed" }],
    });

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", {
        name: "Select event 1 at 0:02.000 seconds",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Nudge +1 frame" }));
    await user.selectOptions(
      screen.getByLabelText("Event type for selected event"),
      "card_moved",
    );
    await user.clear(screen.getByLabelText("Notes for selected event"));
    await user.type(
      screen.getByLabelText("Notes for selected event"),
      "Moved to the table",
    );
    await user.tab();

    await waitFor(() => expect(savedBodies.length).toBeGreaterThan(3));
    const editedEvent = (
      savedBodies.at(-1)?.annotation as {
        events: Array<Record<string, unknown>>;
      }
    ).events[0];
    expect(editedEvent).toMatchObject({
      time_s: expect.closeTo(2 + 1 / 30, 5),
      type: "card_moved",
      confidence: "confirmed",
      notes: "Moved to the table",
    });

    await user.click(
      screen.getByRole("button", { name: "Remove selected event" }),
    );
    await waitFor(() => {
      const lastBody = savedBodies.at(-1);
      expect(lastBody?.annotation).toMatchObject({ events: [] });
    });
    expect(
      screen.getByText("Event removed. You can undo this action."),
    ).toBeInTheDocument();
  });

  it("keeps proposal decisions separate and exposes a retry after a failed save", async () => {
    let revision = 0;
    let failNextSave = true;
    const requests: Array<{ method: string; body?: Record<string, unknown> }> =
      [];
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const method = init?.method ?? "GET";
      if (method === "PUT") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        requests.push({ method, body });
        if (failNextSave) {
          failNextSave = false;
          return Promise.resolve(
            new Response(
              JSON.stringify({
                error: {
                  code: "card_event_review_conflict",
                  message: "Winning draft loaded.",
                },
              }),
              { status: 409, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        revision += 1;
        const proposalDecisions = body.proposals as Array<{
          proposal_id: string;
          decision: "undecided" | "accepted" | "dismissed";
        }>;
        return Promise.resolve(
          response(
            reviewResponse(
              body.annotation
                ? (
                    body.annotation as {
                      events: Array<Record<string, unknown>>;
                    }
                  ).events
                : [],
              [proposalOne, proposalTwo].map((proposal) => ({
                ...proposal,
                decision:
                  proposalDecisions.find(
                    (item) => item.proposal_id === proposal.proposal_id,
                  )?.decision ?? "undecided",
              })),
              revision,
            ),
          ),
        );
      }
      if (method === "GET" && requests.length > 0) {
        return Promise.resolve(
          response(reviewResponse([], [proposalOne, proposalTwo], revision)),
        );
      }
      return Promise.resolve(response(reviewResponse()));
    });
    renderEditor(fetchMock);

    const user = userEvent.setup();
    const proposalOneRow = await screen.findByRole("listitem", {
      name: /Proposal at 0:01\.500 seconds/,
    });
    await user.click(
      within(proposalOneRow).getByRole("button", {
        name: "Accept proposal",
      }),
    );

    expect(
      await screen.findByText(/Conflict: your local action was not saved/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry last save" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry last save" }));

    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]?.body?.proposals).toEqual([
      { proposal_id: "proposal-one", decision: "accepted" },
      { proposal_id: "proposal-two", decision: "undecided" },
    ]);
    expect(
      await screen.findByText("The local action was retried and saved."),
    ).toBeInTheDocument();

    const proposalTwoRow = screen.getByRole("listitem", {
      name: /Proposal at 0:03\.000 seconds/,
    });
    await user.click(
      within(proposalTwoRow).getByRole("button", {
        name: "Dismiss proposal",
      }),
    );
    await waitFor(() => expect(requests).toHaveLength(3));
    expect(requests[2]?.body?.proposals).toEqual([
      { proposal_id: "proposal-one", decision: "accepted" },
      { proposal_id: "proposal-two", decision: "dismissed" },
    ]);
    expect(
      await screen.findByText("Proposal dismissed without creating an event."),
    ).toBeInTheDocument();
  });

  it("requires full-video acknowledgement and proposal decisions, then supports immutable revision", async () => {
    let currentReview = reviewResponse();
    const requests: Array<{
      method: string;
      url: string;
      body?: Record<string, unknown>;
    }> = [];
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const method = init?.method ?? "GET";
      const url = String(input);
      if (method === "PUT") {
        const body = JSON.parse(String(init?.body)) as {
          annotation: { events: Array<Record<string, unknown>> };
          proposals: Array<{ proposal_id: string; decision: ProposalDecision }>;
          full_video_acknowledged: boolean;
        };
        requests.push({ method, url, body: body as Record<string, unknown> });
        currentReview = reviewResponse(
          body.annotation.events,
          currentReview.proposals.map((proposal) => ({
            ...proposal,
            decision:
              body.proposals.find(
                (item) => item.proposal_id === proposal.proposal_id,
              )?.decision ?? proposal.decision,
          })),
          currentReview.draft_revision + 1,
          { full_video_acknowledged: body.full_video_acknowledged },
        );
        return Promise.resolve(response(currentReview));
      }
      if (method === "POST" && url.endsWith("/complete")) {
        const body = JSON.parse(String(init?.body)) as {
          reviewer: string;
          expected_revision: number;
          full_video_acknowledged: boolean;
        };
        requests.push({ method, url, body: body as Record<string, unknown> });
        currentReview = {
          ...currentReview,
          review_state: "completed",
          full_video_acknowledged: body.full_video_acknowledged,
          reviewer: body.reviewer,
          completed_at: "2026-09-01T08:00:00Z",
          completed_version_id: "cardevent-reviewed-version-1",
          completed_version_digest: "c".repeat(64),
          reviewed_annotation_digest: "d".repeat(64),
          proposal_decision_digest: "e".repeat(64),
          completion_receipt_id: "receipt-cardevent-review-1",
        };
        return Promise.resolve(response(currentReview));
      }
      if (method === "POST" && url.endsWith("/revisions")) {
        const body = JSON.parse(String(init?.body)) as {
          parent_version_id: string;
          expected_revision: number;
        };
        requests.push({ method, url, body: body as Record<string, unknown> });
        currentReview = {
          ...currentReview,
          draft_revision: currentReview.draft_revision + 1,
          review_state: "draft",
          full_video_acknowledged: false,
          reviewer: null,
          completed_at: null,
          completed_version_id: null,
          completed_version_digest: null,
          reviewed_annotation_digest: null,
          proposal_decision_digest: null,
          completion_receipt_id: null,
          parent_version_id: body.parent_version_id,
          parent_digest: "c".repeat(64),
        };
        return Promise.resolve(response(currentReview));
      }
      return Promise.resolve(response(currentReview));
    });
    renderEditor(fetchMock);

    const user = userEvent.setup();
    const completeButton = await screen.findByRole("button", {
      name: "Complete full recording review",
    });
    expect(completeButton).toBeDisabled();
    expect(
      screen.getByText(
        /Remaining proposal decisions \(2\): 0:01\.500, 0:03\.000/,
      ),
    ).toBeInTheDocument();

    const video = await screen.findByLabelText(
      "CardEvent source video recording-card-events",
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

    const acknowledgement = screen.getByRole("checkbox");
    await waitFor(() => expect(acknowledgement).toBeEnabled());
    await user.click(acknowledgement);
    await waitFor(() =>
      expect(requests.some((request) => request.method === "PUT")).toBe(true),
    );

    await user.click(
      within(
        screen.getByRole("listitem", {
          name: /Proposal at 0:01\.500 seconds/,
        }),
      ).getByRole("button", { name: "Accept proposal" }),
    );
    await user.click(
      within(
        screen.getByRole("listitem", {
          name: /Proposal at 0:03\.000 seconds/,
        }),
      ).getByRole("button", { name: "Dismiss proposal" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("All proposal decisions are complete."),
      ).toBeInTheDocument(),
    );

    await user.type(
      screen.getByRole("textbox", { name: "Reviewer" }),
      "operator",
    );
    expect(completeButton).toBeEnabled();
    await user.click(completeButton);
    await waitFor(() =>
      expect(
        screen.getByText(/This reviewed annotation is immutable/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("cardevent-reviewed-version-1"),
    ).toBeInTheDocument();
    expect(screen.getByText("receipt-cardevent-review-1")).toBeInTheDocument();
    expect(requests.at(-1)?.body).toMatchObject({
      reviewer: "operator",
      expected_revision: currentReview.draft_revision,
      full_video_acknowledged: true,
    });

    await user.click(
      screen.getByRole("button", { name: "Start a new revision" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Complete full recording review" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Revision started from cardevent-reviewed-version-1/),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(requests.at(-1)?.body).toEqual({
      parent_version_id: "cardevent-reviewed-version-1",
      expected_revision: 3,
    });
  });
});
