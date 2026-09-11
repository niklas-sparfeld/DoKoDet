import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  PipelineReferenceItem,
  PipelineReferenceResource,
} from "../api/client";
import { PipelineCardEventEditor } from "./PipelineCardEventEditor";

const recordingId = "recording-pipeline-events";

function eventItem(
  overrides: Partial<PipelineReferenceItem> = {},
): PipelineReferenceItem {
  return {
    item_id: "event-1",
    base_item_id: "event-1",
    review_state: "pending",
    item: {
      event_id: "event-1",
      event_type: "card_state_changed",
      start_us: 1_000_000,
      end_us: 1_200_000,
      model_scores: [],
    },
    ...overrides,
  };
}

function referenceResponse(
  items: PipelineReferenceItem[],
  revision = 1,
  overrides: Partial<PipelineReferenceResource> = {},
): PipelineReferenceResource {
  return {
    recording_id: recordingId,
    content_type: "events",
    state: {
      recording_id: recordingId,
      content_type: "events",
      draft_revision: revision,
      draft_state: "draft",
      source_revision_id: "generated-1",
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: recordingId,
      content_type: "events",
      revision,
      source_revision_id: "generated-1",
      items,
      coverage: null,
      impact: [],
      updated_at: "2026-09-06T00:00:00Z",
    },
    ...overrides,
  };
}

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderReviewed(
  fetchImplementation: typeof fetch,
  durationUs = 5_000_000,
) {
  vi.stubGlobal("fetch", fetchImplementation);
  return render(
    <PipelineCardEventEditor
      recordingId={recordingId}
      durationUs={durationUs}
      generatedRevisionId="generated-1"
      generatedRunId={null}
      view="reviewed"
    />,
  );
}

function putCalls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
}

describe("PipelineCardEventEditor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("adds, corrects, accepts, rejects, and nudges events with integer microseconds", async () => {
    let server = referenceResponse([eventItem()]);
    const savedBodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method !== "PUT") return response(server);
      const payload = JSON.parse(String(init.body)) as {
        operations: Array<Record<string, unknown>>;
      };
      savedBodies.push(payload);
      const operation = payload.operations[0];
      const itemId = operation.item_id;
      let items = server.draft.items;
      if (operation.operation === "add" && isRecord(operation.item)) {
        items = [
          ...items,
          eventItem({
            item_id: String(operation.item.event_id),
            base_item_id: null,
            review_state: "added",
            item: operation.item,
          }),
        ];
      } else if (typeof itemId === "string") {
        items = items.map((item) =>
          item.item_id !== itemId
            ? item
            : {
                ...item,
                review_state:
                  operation.operation === "accept"
                    ? "accepted"
                    : operation.operation === "reject"
                      ? "rejected"
                      : "corrected",
                item: isRecord(operation.item) ? operation.item : item.item,
              },
        );
      }
      server = referenceResponse(items, server.draft.revision + 1);
      return response(server);
    });

    renderReviewed(fetchMock);
    await screen.findByRole("heading", { name: "CardEvent review" });

    fireEvent.click(screen.getByRole("button", { name: "Accept suggestion" }));
    await waitFor(() => expect(savedBodies).toHaveLength(1));
    expect(savedBodies[0]?.operations).toEqual([
      { operation: "accept", item_id: "event-1" },
    ]);

    const startInput = screen.getByRole("spinbutton", {
      name: "Start time for selected event",
    });
    fireEvent.change(startInput, { target: { value: "1.1" } });
    await waitFor(() => expect(savedBodies).toHaveLength(2));
    expect(savedBodies[1]?.operations).toEqual([
      {
        operation: "correct",
        item_id: "event-1",
        item: expect.objectContaining({ start_us: 1_100_000 }),
      },
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Nudge +1 frame" }));
    await waitFor(() => expect(savedBodies).toHaveLength(3));
    expect(savedBodies[2]?.operations).toEqual([
      {
        operation: "correct",
        item_id: "event-1",
        item: expect.objectContaining({
          start_us: 1_133_333,
          end_us: 1_233_333,
        }),
      },
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Remove event" }));
    await waitFor(() => expect(savedBodies).toHaveLength(4));
    expect(savedBodies[3]?.operations).toEqual([
      { operation: "reject", item_id: "event-1" },
    ]);

    const video = screen.getByLabelText(
      `CardEvent source video ${recordingId}`,
    );
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 2.5,
      writable: true,
    });
    fireEvent.timeUpdate(video);
    fireEvent.click(
      screen.getByRole("button", { name: "Add event at playhead" }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(5));
    const addOperation = (
      savedBodies[4]?.operations as Array<Record<string, unknown>> | undefined
    )?.[0];
    if (addOperation === undefined)
      throw new Error("add operation was not saved");
    expect(addOperation).toMatchObject({ operation: "add" });
    expect((addOperation.item as Record<string, unknown>).start_us).toBe(
      2_500_000,
    );
    expect(
      Number.isInteger((addOperation.item as Record<string, unknown>).start_us),
    ).toBe(true);
    expect(putCalls(fetchMock)).toHaveLength(5);
  });

  it("retries a transient save with the same command and resumes after a revision conflict", async () => {
    let server = referenceResponse([eventItem()]);
    let putCount = 0;
    const putBodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method !== "PUT") return response(server);
      const payload = JSON.parse(String(init.body)) as Record<string, unknown>;
      putBodies.push(payload);
      putCount += 1;
      if (putCount === 1) throw new Error("network temporarily unavailable");
      if (putCount === 2) {
        server = referenceResponse([eventItem()], 2);
        return response({ error: { message: "revision changed" } }, 409);
      }
      server = referenceResponse([eventItem({ review_state: "accepted" })], 3);
      return response(server);
    });

    renderReviewed(fetchMock);
    await screen.findByRole("heading", { name: "CardEvent review" });
    fireEvent.click(screen.getByRole("button", { name: "Accept suggestion" }));

    await screen.findByRole("button", {
      name: "Reload winning draft and retry",
    });
    expect(putBodies[0]?.command_id).toBeTruthy();
    expect(putBodies[1]?.command_id).toBe(putBodies[0]?.command_id);

    fireEvent.click(
      screen.getByRole("button", { name: "Reload winning draft and retry" }),
    );
    await waitFor(() => expect(putBodies).toHaveLength(3));
    expect(putBodies[2]?.expected_revision).toBe(2);
    expect(putBodies[2]?.command_id).toBe(putBodies[0]?.command_id);
  });

  it("keeps selected generated results read-only and does not mutate the draft", async () => {
    const result = {
      run_id: "run-1",
      recording_id: recordingId,
      processor_type: "card-event-detector",
      status: "completed",
      attempt: 1,
      request: {},
      state: {},
      revisions: [
        {
          manifest: { revision_id: "generated-1" },
          content: {
            schema_version: "event-data/v1",
            events: [
              {
                event_id: "generated-event-1",
                event_type: "card_state_changed",
                start_us: 2_000_001,
                end_us: 2_100_001,
              },
            ],
          },
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(result)),
    );

    vi.stubGlobal("fetch", fetchMock);
    render(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={5_000_000}
        generatedRevisionId="generated-1"
        generatedRunId="run-1"
        view="generated"
      />,
    );

    expect(await screen.findByText("0:02.000001")).toBeInTheDocument();
    expect(
      screen.getByText(/Generated events are immutable suggestions/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("CardEvent generated result source video"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/pipeline/events/run-1/result",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBeUndefined();
  });

  it("renders the selected generated event in the inspector", async () => {
    const result = {
      run_id: "run-1",
      recording_id: recordingId,
      processor_type: "card-event-detector",
      status: "completed",
      attempt: 1,
      request: {},
      state: {},
      revisions: [
        {
          manifest: { revision_id: "generated-1" },
          content: {
            schema_version: "event-data/v1",
            events: [
              {
                event_id: "generated-event-1",
                event_type: "card_state_changed",
                start_us: 2_000_001,
                end_us: 2_100_001,
              },
              {
                event_id: "generated-event-2",
                event_type: "card_state_changed",
                start_us: 3_000_001,
                end_us: 3_100_001,
              },
            ],
          },
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(result)),
    );

    vi.stubGlobal("fetch", fetchMock);
    render(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={5_000_000}
        generatedRevisionId="generated-1"
        generatedRunId="run-1"
        selectionItemId="generated-event-2"
        view="generated"
      />,
    );

    expect(
      await screen.findByText("Card-state change at 0:03.000001"),
    ).toBeInTheDocument();
    expect(screen.getByText("0:03.000001")).toBeInTheDocument();
  });

  it("reports maintained event rail items and the selected event", async () => {
    const server = referenceResponse([eventItem()]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(server)),
    );
    const onRailItemsChange = vi.fn();

    vi.stubGlobal("fetch", fetchMock);
    render(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={5_000_000}
        generatedRevisionId="generated-1"
        generatedRunId={null}
        view="reviewed"
        onRailItemsChange={onRailItemsChange}
      />,
    );

    expect(
      await screen.findByText("Card-state change at 0:01.000000"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(onRailItemsChange).toHaveBeenLastCalledWith([
        {
          itemId: "event-1",
          label: "Card-state change",
          state: "pending",
          startUs: 1_000_000,
          endUs: 1_200_000,
        },
      ]),
    );
  });

  it("uses the source video and Timeline Rail selection instead of an event table", async () => {
    const server = referenceResponse([eventItem()]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(server)),
    );

    renderReviewed(fetchMock);
    await screen.findByRole("heading", { name: "CardEvent review" });

    expect(
      screen.getByLabelText(`CardEvent source video ${recordingId}`),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Event timeline")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Select an event from the timeline or table."),
    ).not.toBeInTheDocument();
  });

  it("requires complete coverage before publishing and sends full-recording microseconds", async () => {
    const draft = referenceResponse(
      [eventItem({ review_state: "accepted" })],
      4,
    );
    const completed = referenceResponse(
      [eventItem({ review_state: "accepted" })],
      5,
      {
        state: {
          ...draft.state,
          draft_revision: 5,
          draft_state: "completed",
          selected_completed_revision_id: "events-completed-1",
        },
      },
    );
    let completionPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "POST") {
        completionPayload = JSON.parse(String(init.body)) as Record<
          string,
          unknown
        >;
        return response(completed);
      }
      return response(draft);
    });

    renderReviewed(fetchMock, 3_000_000);
    await screen.findByRole("heading", { name: "CardEvent review" });
    const completeButton = screen.getByRole("button", {
      name: "Complete reference",
    });
    expect(completeButton).toBeDisabled();
    expect(
      screen.getByText(
        "Watch the complete recording to record full-video coverage.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("operator-01"), {
      target: { value: "operator-1" },
    });
    fireEvent.change(screen.getByPlaceholderText("reviewer-01"), {
      target: { value: "reviewer-1" },
    });
    const video = screen.getByLabelText(
      `CardEvent source video ${recordingId}`,
    );
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      value: 3,
      writable: true,
    });
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(completeButton).not.toBeDisabled());

    fireEvent.click(completeButton);
    await waitFor(() => expect(completionPayload).not.toBeNull());
    expect(completionPayload).toEqual({
      expected_revision: 4,
      operator_id: "reviewer-1",
      coverage: {
        kind: "full_recording",
        intervals: [{ start_us: 0, end_us: 3_000_000 }],
      },
    });
  });
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
