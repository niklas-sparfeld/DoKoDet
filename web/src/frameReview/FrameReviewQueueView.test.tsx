import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FrameReviewEditorNavigation,
  FrameReviewPinnedRevisionNotice,
  FrameReviewQueueView,
} from "./FrameReviewQueueView";

afterEach(() => vi.unstubAllGlobals());

function queueItem(overrides: Record<string, unknown> = {}) {
  const recordingId = "recording-one";
  const itemId = "event-1";
  return {
    recording_id: recordingId,
    item_id: itemId,
    state: "pending",
    reasons: ["overlapping_card_candidates"],
    eligible: true,
    comparison_eligible: false,
    unavailable_reason: null,
    editor_target: {
      path: `/recordings/${recordingId}/pipeline/visible_cards?view=generated&revision=revision-1&item=${itemId}`,
      revision_id: "revision-1",
      item_id: itemId,
      scene_run_id: "scene-run-1",
      scene_revision_id: null,
    },
    ...overrides,
  };
}

function page(items: unknown[]) {
  return {
    schema_version: "frame-review-page/v1",
    queue_id: "0096-M4",
    queue_digest: "digest",
    items,
    counts: {
      total: items.length,
      by_state: {
        pending: items.length,
        deferred: 0,
        saved_review: 0,
        unavailable: 0,
      },
      by_reason: {},
    },
    next_cursor: null,
    resume_recording_id: null,
    resume_item_id: null,
  };
}

describe("frame review queue", () => {
  it("shows reasons, exact pinned navigation, and detector-only scene state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(page([queueItem()])), { status: 200 }),
        ),
      ),
    );

    render(<FrameReviewQueueView />);

    const open = await screen.findByRole("link", { name: "Open exact result" });
    expect(open).toHaveAttribute(
      "href",
      "/recordings/recording-one/pipeline/visible_cards?view=generated&revision=revision-1&item=event-1&frame_review=0096-M4",
    );
    expect(
      screen.getByText(
        "Detector result only. Proposed scene output is unavailable for this frame.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("overlapping card candidates")).toBeInTheDocument();
  });

  it("navigates to neighboring frames across recordings", async () => {
    const first = queueItem();
    const second = queueItem({
      recording_id: "recording-two",
      item_id: "event-2",
      editor_target: {
        path: "/recordings/recording-two/pipeline/visible_cards?view=generated&revision=revision-2&item=event-2",
        revision_id: "revision-2",
        item_id: "event-2",
        scene_run_id: null,
        scene_revision_id: null,
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(page([first, second])), { status: 200 }),
        ),
      ),
    );
    window.history.replaceState(
      {},
      "",
      "/recordings/recording-one/pipeline/visible_cards?frame_review=0096-M4&revision=revision-1&item=event-1",
    );

    render(
      <FrameReviewEditorNavigation
        recordingId="recording-one"
        itemId="event-1"
      />,
    );

    expect(
      await screen.findByText("Frame 1 of 2 · recording-one · event-1"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Next →" })).toHaveAttribute(
      "href",
      "/recordings/recording-two/pipeline/visible_cards?view=generated&revision=revision-2&item=event-2&frame_review=0096-M4",
    );
    expect(
      screen.getByRole("link", { name: "Return to frame list" }),
    ).toHaveAttribute("href", "/frame-reviews/0096-M4");
  });

  it("keeps unavailable items visible and does not offer editor navigation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              page([
                queueItem({
                  state: "unavailable",
                  unavailable_reason: "The pinned detector result is missing.",
                }),
              ]),
            ),
            { status: 200 },
          ),
        ),
      ),
    );

    render(<FrameReviewQueueView />);

    expect(
      await screen.findByText("The pinned detector result is missing."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Open exact result" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("defers a pending frame and reloads its persisted queue state", async () => {
    const deferredPage = page([queueItem({ state: "deferred" })]);
    let wasDeferred = false;
    const fetchMock = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        wasDeferred = true;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              queue_id: "0096-M4",
              queue_digest: "digest",
              deferred: true,
              resume_recording_id: null,
              resume_item_id: null,
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify(wasDeferred ? deferredPage : page([queueItem()])),
          { status: 200 },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<FrameReviewQueueView />);
    fireEvent.click(await screen.findByRole("button", { name: "Defer" }));

    await waitFor(() =>
      expect(screen.getByText("Frame event-1 · Deferred")).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/frame-reviews/0096-M4/items/recording-one/event-1/workflow",
      expect.objectContaining({ method: "PUT" }),
    );
  });

  it("identifies the frozen result when the current selection has moved", () => {
    render(
      <FrameReviewPinnedRevisionNotice
        pinnedRevision="frozen-revision"
        selectedRevision="new-revision"
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Viewing frozen queue result frozen-revision",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "current generated selection is new-revision",
    );
  });
});
