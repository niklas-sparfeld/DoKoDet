import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PipelineNodeEventEditor } from "./PipelineNodeEventEditor";
import { resetWorkingAreaFrameCacheForTests } from "../workingArea/workingAreaFrame";

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

  it("shows exact still frames and keeps event controls outside the surface", async () => {
    resetWorkingAreaFrameCacheForTests();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:exact-frame");
    const sourceSha256 = "a".repeat(64);
    const requestedFrames: string[] = [];
    const fetchMock = vi.fn(
      async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.includes("/derived-views/exact-event/")) {
          requestedFrames.push(path);
          const requestedTimeUs = Number(path.split("?")[0]?.split("/").at(-1));
          const frameIndex =
            new URL(path, "http://localhost").searchParams.get("frame_index") ??
            "4";
          return new Response(new Blob(["still"]), {
            status: 200,
            headers: {
              ETag: `"${"b".repeat(64)}"`,
              "X-DokoDetector-Source-Sha256": sourceSha256,
              "X-DokoDetector-Frame-Index": frameIndex,
              "X-DokoDetector-Frame-Width": "640",
              "X-DokoDetector-Frame-Height": "360",
              "X-DokoDetector-Requested-Time-Us": String(requestedTimeUs),
              "X-DokoDetector-Frame-Time-Us": String(requestedTimeUs),
            },
          });
        }
        if (path.endsWith("/reviews")) return jsonResponse([]);
        if (path.endsWith("/edit"))
          return jsonResponse({
            node_id: "events",
            revision_id: "r2",
            copied: false,
            name: "First pass",
          });
        if (path.endsWith("/revisions/r1")) return jsonResponse(revision);
        throw new Error(`Unexpected fetch ${path} ${String(init?.method)}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const onPositionChange = vi.fn();
    const editor = (selectionTimeUs: number | null) => (
      <>
        <div data-event-inspector-slot="action" />
        <div data-timeline-seeking-slot="true" />
        <PipelineNodeEventEditor
          recordingId="recording-1"
          nodeId="events"
          revisionId="r1"
          durationUs={1_000_000}
          sourceSha256={sourceSha256}
          portalToInspector
          selectionItemId="event-1"
          selectionTimeUs={selectionTimeUs}
          onRevisionChange={vi.fn()}
          onPositionChange={onPositionChange}
        />
      </>
    );
    const { rerender } = render(editor(400_000));

    const surface = await screen.findByRole("region", {
      name: "Spatial evidence surface",
    });
    expect(
      await screen.findByRole("img", { name: "Source frame" }),
    ).toHaveAttribute("src", "blob:exact-frame");
    expect(surface.querySelector("video")).toBeNull();
    expect(surface.textContent).toBe("");
    expect(requestedFrames).toContain(
      "/api/recordings/recording-1/pipeline/derived-views/exact-event/400000",
    );

    fireEvent.click(await screen.findByRole("button", { name: /Next frame/ }));
    await waitFor(() =>
      expect(requestedFrames).toContain(
        "/api/recordings/recording-1/pipeline/derived-views/exact-event/400000?frame_index=5",
      ),
    );
    await waitFor(() =>
      expect(onPositionChange).toHaveBeenCalledWith(null, 400_000),
    );

    fireEvent.click(await screen.findByRole("button", { name: "event-1" }));
    expect(onPositionChange).toHaveBeenCalledWith("event-1", 100);
    rerender(editor(100));
    await waitFor(() =>
      expect(requestedFrames).toContain(
        "/api/recordings/recording-1/pipeline/derived-views/exact-event/100",
      ),
    );

    fireEvent.change(await screen.findByLabelText("Start (µs)"), {
      target: { value: "150" },
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/pipeline/nodes/events/edit",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("shows retained rejected events without adding them to the event content", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          ...revision,
          metadata: {
            excluded_items: [
              { item_id: "event-rejected", decision: "rejected" },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse([
          {
            review_id: "review-rejected-second",
            kind: "item",
            item_id: "event-rejected-second",
            decision: "rejected",
          },
        ]),
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
    expect(
      await screen.findByText("Retained rejected events (2)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("event-rejected · rejected in an earlier review"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("event-rejected-second · rejected in an earlier review"),
    ).toBeInTheDocument();
  });

  it("does not label partial retained coverage as a full recording review", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(
        jsonResponse([
          {
            kind: "coverage",
            review_id: "coverage-1",
            decision: null,
            coverage: {
              kind: "full_recording",
              intervals: [{ start_us: 0, end_us: 500_000 }],
            },
          },
        ]),
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
    await screen.findByLabelText("Start (µs)");
    expect(
      screen.queryByRole("button", { name: "Full recording reviewed" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Record overall acceptance" }),
    ).toBeDisabled();
  });

  it("shows a retained corrected item as reviewed", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(
        jsonResponse([
          {
            kind: "item",
            review_id: "review-1",
            item_id: "event-1",
            decision: "corrected",
          },
        ]),
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
    expect(await screen.findByText("corrected")).toBeInTheDocument();
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
      screen.getByRole("button", { name: "Add event at timeline cursor" }),
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
      await screen.findByRole("button", {
        name: "Add event at timeline cursor",
      }),
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
