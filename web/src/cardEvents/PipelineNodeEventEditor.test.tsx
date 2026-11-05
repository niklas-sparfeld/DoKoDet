import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PipelineNodeEventEditor } from "./PipelineNodeEventEditor";

const revision = {
  node_id: "events",
  name: "First pass",
  content_type: "events",
  source: { video_sha256: "a".repeat(64) },
  head_revision_id: "r1",
  revision_id: "r1",
  content: {
    schema_version: "event-data/v1",
    events: [
      {
        event_id: "event-1",
        event_type: "card_state_changed",
        start_us: 100,
        end_us: 200,
      },
    ],
  },
};

describe("PipelineNodeEventEditor", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("crypto", {
      randomUUID: vi
        .fn()
        .mockReturnValueOnce("edit-key")
        .mockReturnValueOnce("review-key"),
    });
  });

  it("loads one exact node revision and saves an edit with item provenance", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "events-copy",
          revision_id: "r2",
          copied: true,
          reason: "downstream_use",
          name: "First pass copy",
        }),
      );
    const onRevisionChange = vi.fn();
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={onRevisionChange}
        onPositionChange={vi.fn()}
      />,
    );

    const start = await screen.findByLabelText("Start (µs)");
    fireEvent.change(start, { target: { value: "150" } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const [, request] = fetchMock.mock.calls[2] as [string, RequestInit];
    const body = JSON.parse(request.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({
      expected_revision_id: "r1",
      idempotency_key: "edit-key",
      pointers: { "event-1": "/events/0" },
      base_pointers: { "event-1": "/events/0" },
      operations: [
        { kind: "replace", before: ["event-1"], after: ["event-1"] },
      ],
    });
    expect(onRevisionChange).toHaveBeenCalledWith(
      "events",
      "r1",
      "events-copy",
      "r2",
      "event-1",
      0,
    );
    expect(
      await screen.findByText(/Created First pass copy from First pass/),
    ).toBeInTheDocument();
  });

  it("keeps historical revisions read-only", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({ ...revision, head_revision_id: "r2" }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={vi.fn()}
        onPositionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText("This revision is historical and read-only."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Start (µs)")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Add event at playhead" }),
    ).toBeDisabled();
  });

  it("records an item rejection as a review decision without deleting content", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn().mockReturnValue("review-key"),
    });
    const rejectedReview = {
      kind: "item",
      review_id: "review-key",
      item_id: "event-1",
      decision: "rejected",
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse(rejectedReview))
      .mockResolvedValueOnce(jsonResponse([rejectedReview]));
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={vi.fn()}
        onPositionChange={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(fetchMock.mock.calls[2]?.[0]).toContain("/reviews/item");
    const request = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      revision_id: "r1",
      item_id: "event-1",
      decision: "rejected",
    });
    expect(await screen.findByText("rejected")).toBeInTheDocument();
    expect(screen.getByLabelText("Start (µs)")).toHaveValue(100);
  });

  it("records an event deletion as a content edit with provenance", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "events",
          revision_id: "r2",
          copied: false,
          name: "First pass",
        }),
      );
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={vi.fn()}
        onPositionChange={vi.fn()}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete event" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const request = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      pointers: {},
      base_pointers: { "event-1": "/events/0" },
      operations: [{ kind: "delete", before: ["event-1"], after: [] }],
      content: { events: [] },
    });
  });

  it("records a human-added event as an insert operation", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "events",
          revision_id: "r2",
          copied: false,
          name: "First pass",
        }),
      );
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={vi.fn()}
        onPositionChange={vi.fn()}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Add event at playhead" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const request = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      operations: [{ kind: "insert", before: [], after: ["edit-key"] }],
      content: { events: [{ event_id: "event-1" }, { event_id: "edit-key" }] },
    });
  });

  it("retries an autosave with the same idempotency key", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "events",
          revision_id: "r2",
          copied: false,
          name: "First pass",
        }),
      );
    render(
      <PipelineNodeEventEditor
        recordingId="recording-1"
        nodeId="events"
        revisionId="r1"
        durationUs={1_000_000}
        selectionItemId="event-1"
        selectionTimeUs={null}
        onRevisionChange={vi.fn()}
        onPositionChange={vi.fn()}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Start (µs)"), {
      target: { value: "150" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    fireEvent.click(await screen.findByRole("button", { name: "Retry save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));

    const keys = fetchMock.mock.calls.slice(2).map(([, request]) => {
      const body = JSON.parse((request as RequestInit).body as string) as {
        idempotency_key: string;
      };
      return body.idempotency_key;
    });
    expect(keys).toEqual(["edit-key", "edit-key", "edit-key", "edit-key"]);
  });
});

function jsonResponse(value: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => value,
  } as Response;
}

function errorResponse(status: number): Response {
  return { ok: false, status, json: async () => ({}) } as Response;
}
