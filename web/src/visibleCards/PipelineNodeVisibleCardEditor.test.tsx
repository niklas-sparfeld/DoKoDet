import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineNodeVisibleCardEditor } from "./PipelineNodeVisibleCardEditor";

vi.mock("../profile/profile", () => ({
  useProfileName: () => "Review Person",
}));

const revision = {
  node_id: "visible-cards",
  name: "Detector output",
  content_type: "visible_cards",
  head_revision_id: "r1",
  revision_id: "r1",
  parent_revision_id: null,
  metadata: {},
  created_at: "2026-11-05T10:00:00Z",
  content: {
    schema_version: "visible-card-data/v2",
    outcomes: [
      {
        event_id: "event-1",
        frame_identity: {
          requested_time_us: 250_000,
          source_video_sha256: "a".repeat(64),
        },
        status: "detected",
        candidates: [{ card_id: "card-1" }],
        ignored_regions: [],
        pile_regions: [],
        pile_detection_status: "supported",
        error: null,
      },
    ],
  },
};

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PipelineNodeVisibleCardEditor", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn().mockReturnValue("stable-key"),
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(revision)));
  });

  it("explains frames that have scene data but no visible regions", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          ...revision,
          metadata: { legacy_review: { scene_only_items: ["event-1"] } },
          content: { schema_version: "visible-card-data/v2", outcomes: [] },
        }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId={null}
        selectionTimeUs={null}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(/Open Virtual scenes to inspect 1 frame/),
    ).toBeInTheDocument();
  });

  it("loads the selected revision, edits one outcome, and selects the returned copy", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "copy-1",
          revision_id: "r2",
          copied: true,
          name: "Detector output copy",
        }),
      );
    const onRevisionChange = vi.fn();
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId="event-1"
        selectionTimeUs={250_000}
        onPositionChange={vi.fn()}
        onRevisionChange={onRevisionChange}
      />,
    );

    const candidates = await screen.findByLabelText("candidates JSON");
    fireEvent.change(candidates, {
      target: { value: '[{"card_id":"card-1","edited":true}]' },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save visible-card changes" }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const request = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      expected_revision_id: "r1",
      actor: { kind: "human", id: "Review-Person" },
      base_pointers: { "event-1": "/outcomes/0" },
      pointers: { "event-1": "/outcomes/0" },
      operations: [
        { kind: "replace", before: ["event-1"], after: ["event-1"] },
      ],
    });
    expect(onRevisionChange).toHaveBeenCalledWith(
      "visible-cards",
      "r1",
      "copy-1",
      "r2",
      "event-1",
      250_000,
    );
  });

  it("keeps historical visible-card content read-only", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({ ...revision, head_revision_id: "r2" }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId="event-1"
        selectionTimeUs={null}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText("Historical revision · read only"),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("candidates JSON")).toHaveAttribute(
      "readonly",
    );
    expect(
      screen.queryByRole("button", { name: "Save visible-card changes" }),
    ).not.toBeInTheDocument();
  });

  it("does not fall back when the URL names a missing outcome", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId="deleted-outcome"
        selectionTimeUs={null}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "The selected outcome is not present in this revision. No other outcome was selected.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "The selected outcome is unavailable in this revision.",
    );
  });

  it("records item acceptance against the selected exact revision", async () => {
    const fetchMock = vi.mocked(fetch);
    const onReview = vi.fn();
    window.addEventListener("frame-review-node-reviewed", onReview);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({ kind: "item", decision: "accepted" }),
      );
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId="event-1"
        selectionTimeUs={null}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Accept outcome" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[0]).toContain("/reviews/item");
    expect(
      JSON.parse((fetchMock.mock.calls[2]?.[1] as RequestInit).body as string),
    ).toMatchObject({
      revision_id: "r1",
      item_id: "event-1",
      decision: "accepted",
    });
    await waitFor(() => expect(onReview).toHaveBeenCalledOnce());
    expect((onReview.mock.calls[0][0] as CustomEvent).detail).toMatchObject({
      itemId: "event-1",
      nodeId: "visible-cards",
      revisionId: "r1",
      reviewId: "visible-cards-accept-stable-key",
    });
    window.removeEventListener("frame-review-node-reviewed", onReview);
  });

  it("requires each outcome to be marked inspected before recording full coverage", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({ kind: "coverage", review_id: "coverage" }),
      );
    render(
      <PipelineNodeVisibleCardEditor
        recordingId="recording-1"
        nodeId="visible-cards"
        revisionId="r1"
        selectionItemId="event-1"
        selectionTimeUs={null}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    const coverage = await screen.findByRole("button", {
      name: "Accept full-recording coverage",
    });
    expect(coverage).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Mark frame inspected" }),
    );
    expect(coverage).toBeEnabled();
    fireEvent.click(coverage);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2]?.[0]).toContain("/reviews/coverage");
    expect(
      JSON.parse((fetchMock.mock.calls[2]?.[1] as RequestInit).body as string),
    ).toMatchObject({
      revision_id: "r1",
      coverage: { complete: true, reviewed_item_ids: ["event-1"] },
      evidence: { inspected_item_ids: ["event-1"] },
    });
  });
});
