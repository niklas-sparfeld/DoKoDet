import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

function emptyReferenceResponse(): PipelineReferenceResource {
  const response = referenceResponse([], 0);
  return {
    ...response,
    state: { ...response.state, source_revision_id: null },
    draft: { ...response.draft, source_revision_id: null },
  };
}

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function frameImageResponse(): Response {
  return new Response(Uint8Array.from([1, 2, 3, 4]), {
    status: 200,
    headers: { "Content-Type": "image/jpeg" },
  });
}

function videoFileResponse(): Response {
  return new Response(Uint8Array.from([0, 1, 2, 3]), {
    status: 200,
    headers: {
      "Content-Type": "video/mp4",
      "Content-Length": "4",
    },
  });
}

function withReviewFrames(fetchImplementation: typeof fetch): typeof fetch {
  return async (input, init) => {
    const url = String(input);
    if (url.includes("/derived-views/")) return frameImageResponse();
    if (url.includes("/repository-bundles/") && url.endsWith("/video")) {
      return videoFileResponse();
    }
    return fetchImplementation(input, init);
  };
}

function renderReviewed(
  fetchImplementation: typeof fetch,
  durationUs = 5_000_000,
  selectionTimeUs?: number | null,
) {
  vi.stubGlobal("fetch", withReviewFrames(fetchImplementation));
  return render(
    <PipelineCardEventEditor
      recordingId={recordingId}
      durationUs={durationUs}
      selectionTimeUs={selectionTimeUs}
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
    window.history.replaceState({}, "", "/");
  });

  it("adds, accepts, dismisses, and nudges events with integer microseconds", async () => {
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

    const rendered = renderReviewed(fetchMock);
    const controls = await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });

    fireEvent.click(within(controls).getByRole("button", { name: "Accept A" }));
    await waitFor(() => expect(savedBodies).toHaveLength(1));
    expect(savedBodies[0]?.operations).toEqual([
      { operation: "accept", item_id: "event-1" },
    ]);

    fireEvent.click(
      within(controls).getByRole("button", { name: "Nudge later ." }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(2));
    expect(savedBodies[1]?.operations).toEqual([
      {
        operation: "correct",
        item_id: "event-1",
        item: expect.objectContaining({
          start_us: 1_033_333,
          end_us: 1_233_333,
        }),
      },
    ]);
    expect(window.location.search).toContain("t_us=1033333");

    fireEvent.click(
      within(controls).getByRole("button", { name: "Dismiss D" }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(3));
    expect(savedBodies[2]?.operations).toEqual([
      {
        operation: "reject",
        item_id: "event-1",
      },
    ]);

    rendered.rerender(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={5_000_000}
        selectionTimeUs={2_500_000}
        generatedRevisionId="generated-1"
        generatedRunId={null}
        view="reviewed"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-requested-time-us", "2500000"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Add event at playhead" }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(4));
    const addOperation = (
      savedBodies[3]?.operations as Array<Record<string, unknown>> | undefined
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
    expect(putCalls(fetchMock)).toHaveLength(4);
  });

  it("updates the playhead URL on nudge without broadcasting popstate", async () => {
    const server = referenceResponse([eventItem()]);
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as {
          operations?: Array<Record<string, unknown>>;
        };
        const operation = payload.operations?.[0];
        if (
          operation?.operation === "correct" &&
          isRecord(operation.item) &&
          typeof operation.item_id === "string"
        ) {
          return response(
            referenceResponse(
              [
                {
                  ...eventItem(),
                  review_state: "corrected",
                  item: operation.item,
                },
              ],
              2,
            ),
          );
        }
      }
      return response(server);
    });
    const popstate = vi.fn();
    window.addEventListener("popstate", popstate);
    renderReviewed(fetchMock);
    const controls = await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
    popstate.mockClear();

    fireEvent.click(
      within(controls).getByRole("button", { name: "Nudge later ." }),
    );
    await waitFor(() =>
      expect(window.location.search).toContain("t_us=1033333"),
    );
    expect(popstate).not.toHaveBeenCalled();
    window.removeEventListener("popstate", popstate);
  });

  it("coalesces rapid nudges while an earlier save is in flight", async () => {
    let server = referenceResponse([eventItem()]);
    const savedBodies: Array<Record<string, unknown>> = [];
    let releaseFirstSave: (() => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method !== "PUT") return response(server);
      const payload = JSON.parse(String(init.body)) as {
        operations?: Array<Record<string, unknown>>;
      };
      savedBodies.push(payload);
      const operation = payload.operations?.[0];
      if (operation === undefined) throw new Error("operation was not saved");
      const itemId = operation.item_id;
      if (operation.operation === "correct" && typeof itemId === "string") {
        const correctedItem = operation.item;
        server = referenceResponse(
          server.draft.items.map((item) =>
            item.item_id === itemId && isRecord(correctedItem)
              ? { ...item, review_state: "corrected", item: correctedItem }
              : item,
          ),
          server.draft.revision + 1,
        );
      }
      const savedResponse = response(server);
      if (savedBodies.length === 1) {
        return new Promise<Response>((resolve) => {
          releaseFirstSave = () => resolve(savedResponse);
        });
      }
      return savedResponse;
    });

    renderReviewed(fetchMock);
    await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });

    fireEvent.keyDown(window, { key: "." });
    await waitFor(() => expect(savedBodies).toHaveLength(1));
    fireEvent.keyDown(window, { key: "." });
    fireEvent.keyDown(window, { key: "." });
    fireEvent.keyDown(window, { key: "." });
    fireEvent.keyDown(window, { key: "." });

    expect(savedBodies).toHaveLength(1);
    expect(
      within(screen.getByLabelText("Selected event interval")).getByText(
        "0:01.166665",
      ),
    ).toBeInTheDocument();

    if (releaseFirstSave === undefined)
      throw new Error("first save was not made releaseable");
    releaseFirstSave();
    await waitFor(() => expect(savedBodies).toHaveLength(2));
    await waitFor(() => expect(server.draft.revision).toBe(3));
    expect(savedBodies[0]?.operations).toEqual([
      {
        operation: "correct",
        item_id: "event-1",
        item: expect.objectContaining({
          start_us: 1_033_333,
          end_us: 1_233_333,
        }),
      },
    ]);
    expect(savedBodies[1]?.operations).toEqual([
      {
        operation: "correct",
        item_id: "event-1",
        item: expect.objectContaining({
          start_us: 1_166_665,
          end_us: 1_366_665,
        }),
      },
    ]);
    expect(server.draft.items[0]?.item.start_us).toBe(1_166_665);
  });

  it("marks a point event start and stable end, then reloads the interval", async () => {
    let server = referenceResponse([]);
    const savedBodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method !== "PUT") return response(server);
      const payload = JSON.parse(String(init.body)) as {
        operations: Array<Record<string, unknown>>;
      };
      savedBodies.push(payload);
      const operation = payload.operations[0];
      const itemId = operation.item_id;
      const correctedItem = isRecord(operation.item) ? operation.item : null;
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
      } else if (
        operation.operation === "correct" &&
        typeof itemId === "string" &&
        correctedItem !== null
      ) {
        items = items.map((item) =>
          item.item_id === itemId
            ? { ...item, review_state: "corrected", item: correctedItem }
            : item,
        );
      }
      server = referenceResponse(items, server.draft.revision + 1);
      return response(server);
    });

    const rendered = renderReviewed(fetchMock, 5_000_000, 1_500_000);
    const controls = await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-requested-time-us", "1500000"),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Add event at playhead" }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(1));
    fireEvent.keyDown(window, { key: "s" });
    await waitFor(() => expect(savedBodies).toHaveLength(2));
    expect(savedBodies[1]?.operations).toEqual([
      {
        operation: "correct",
        item_id: expect.any(String),
        item: expect.objectContaining({
          start_us: 1_500_000,
          end_us: 1_500_000,
        }),
      },
    ]);

    fireEvent.click(
      within(controls).getByRole("button", { name: /Seek right/ }),
    );
    fireEvent.click(
      within(controls).getByRole("button", { name: "Mark stable end E" }),
    );
    await waitFor(() => expect(savedBodies).toHaveLength(3));
    expect(savedBodies[2]?.operations).toEqual([
      {
        operation: "correct",
        item_id: expect.any(String),
        item: expect.objectContaining({
          start_us: 1_500_000,
          end_us: 1_750_000,
        }),
      },
    ]);
    const interval = screen.getByLabelText("Selected event interval");
    expect(within(interval).getByText("0:01.500000")).toBeInTheDocument();
    expect(within(interval).getAllByText("0:01.750000")).not.toHaveLength(0);
    expect(within(interval).getByText("0:00.250000")).toBeInTheDocument();
    expect(within(interval).getAllByText("Stable end")).toHaveLength(2);
    expect(
      screen.getByText(/Stable-end anchor: 0:01.750000\./),
    ).toBeInTheDocument();

    const boundNavigation = screen.getByRole("group", {
      name: "Selected event frame navigation",
    });
    fireEvent.click(
      within(boundNavigation).getByRole("button", {
        name: "Stable end 0:01.750000",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-requested-time-us", "1750000"),
    );
    expect(
      within(boundNavigation).getByRole("button", {
        name: "Stable end 0:01.750000",
      }),
    ).toHaveAttribute("aria-pressed", "true");

    rendered.unmount();
    renderReviewed(fetchMock, 5_000_000, 1_500_000);
    const reloadedInterval = await screen.findByLabelText(
      "Selected event interval",
    );
    expect(
      within(reloadedInterval).getByText("0:01.500000"),
    ).toBeInTheDocument();
    expect(
      within(reloadedInterval).getAllByText("0:01.750000"),
    ).not.toHaveLength(0);
    expect(
      screen.getByRole("group", { name: "Selected event frame navigation" }),
    ).toBeInTheDocument();
  });

  it("rejects a stable end before the start without changing the draft", async () => {
    const server = referenceResponse([
      eventItem({
        item: {
          event_id: "event-1",
          event_type: "card_state_changed",
          start_us: 2_000_000,
          end_us: 2_500_000,
          model_scores: [],
        },
      }),
    ]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(server)),
    );

    renderReviewed(fetchMock, 5_000_000, 1_500_000);
    const controls = await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
    fireEvent.click(
      within(controls).getByRole("button", { name: "Mark stable end E" }),
    );

    expect(
      await screen.findAllByText(
        "Stable end must be at or after the event start.",
      ),
    ).not.toHaveLength(0);
    expect(putCalls(fetchMock)).toHaveLength(0);
    const interval = screen.getByLabelText("Selected event interval");
    expect(within(interval).getAllByText("0:02.500000")).not.toHaveLength(0);
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

    renderReviewed(fetchMock, 5_000_000, 1_000_000);
    const controls = await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
    fireEvent.click(within(controls).getByRole("button", { name: "Accept A" }));

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

  it("seeds an existing empty reference from the generated event result", async () => {
    let server = emptyReferenceResponse();
    const result = {
      run_id: "run-1",
      recording_id: recordingId,
      processor_type: "card-event-detector",
      status: "complete",
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
                start_us: 2_000_000,
                end_us: 2_000_000,
              },
            ],
          },
        },
      ],
    };
    const putBodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method === "PUT") {
        putBodies.push(
          JSON.parse(String(init.body)) as Record<string, unknown>,
        );
        server = referenceResponse(
          [
            eventItem({
              item_id: "generated-event-1",
              base_item_id: null,
              item: {
                event_id: "generated-event-1",
                event_type: "card_state_changed",
                start_us: 2_000_000,
                end_us: 2_000_000,
              },
            }),
          ],
          1,
        );
        return response(server);
      }
      if (String(input).endsWith("/result")) return response(result);
      return response(server);
    });

    vi.stubGlobal("fetch", fetchMock);
    render(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={5_000_000}
        generatedRevisionId="generated-1"
        generatedRunId="run-1"
        view="reviewed"
      />,
    );

    expect(
      await screen.findByRole("button", { name: "Start review" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("1 event")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("operator-01"), {
      target: { value: "operator-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start review" }));

    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0]?.operations).toEqual([
      { operation: "rebase", source_revision_id: "generated-1" },
    ]);
    expect(
      await screen.findByRole("button", { name: "Accept A" }),
    ).toBeEnabled();
    expect(
      screen.getByText("Card-state change at 0:02.000000"),
    ).toBeInTheDocument();
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

  it("uses the exact review frame and Timeline Rail selection instead of an event table", async () => {
    const server = referenceResponse([eventItem()]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(server)),
    );

    renderReviewed(fetchMock, 5_000_000, 1_000_000);

    expect(
      await screen.findByRole("img", {
        name: "CardEvent review frame at 0:01.000000",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Event timeline")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Select an event from the timeline or table."),
    ).not.toBeInTheDocument();
  });

  it("renders reviewed actions in a compact control rail", async () => {
    const server = referenceResponse([
      eventItem(),
      eventItem({
        item_id: "event-2",
        base_item_id: "event-2",
        item: {
          event_id: "event-2",
          event_type: "card_state_changed",
          start_us: 3_000_000,
          end_us: 3_200_000,
          model_scores: [],
        },
      }),
    ]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(server)),
    );

    renderReviewed(fetchMock, 5_000_000, 1_000_000);
    await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-requested-time-us", "1000000"),
    );

    const controls = screen.getByRole("complementary", {
      name: "CardEvent review controls",
    });
    for (const ariaName of [
      /Previous event/,
      /Next event/,
      /Seek left/,
      /Seek right/,
      "Nudge earlier ,",
      "Nudge later .",
      "Mark start S",
      "Mark stable end E",
      "Accept A",
      "Dismiss D",
      "Add event N",
    ]) {
      expect(
        within(controls).getByRole("button", {
          name: ariaName,
        }),
      ).toBeInTheDocument();
    }
    expect(
      within(controls).getByRole("button", { name: /Previous event/ }),
    ).toBeDisabled();
    expect(
      within(controls).getByRole("button", { name: "Nudge earlier ," }),
    ).not.toBeDisabled();
    expect(
      screen.queryByRole("region", { name: "Selected event details" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Keyboard shortcuts")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Review whether a persistent card-related table-state change is visible and set its time to the first clear frame.",
      ),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(controls).getByRole("button", { name: /Next event/ }),
    );
    expect(window.location.search).toContain("item=event-2");
    expect(window.location.search).toContain("t_us=3000000");

    fireEvent.click(
      within(controls).getByRole("button", { name: /Seek left/ }),
    );
    expect(window.location.search).toContain("t_us=2750000");

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(window.location.search).toContain("item=event-1");
    expect(window.location.search).toContain("t_us=1000000");
    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true });
    expect(window.location.search).toContain("t_us=1250000");
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

    const rendered = renderReviewed(fetchMock, 3_000_000);
    await screen.findByRole("complementary", {
      name: "CardEvent review controls",
    });
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
    rendered.rerender(
      <PipelineCardEventEditor
        recordingId={recordingId}
        durationUs={3_000_000}
        selectionTimeUs={3_000_000}
        generatedRevisionId="generated-1"
        generatedRunId={null}
        view="reviewed"
      />,
    );
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

  it("keeps the corrected-reference action after editing a completed reference", async () => {
    const completedBase = referenceResponse(
      [eventItem({ review_state: "accepted" })],
      5,
    );
    const completed = {
      ...completedBase,
      state: {
        ...completedBase.state,
        draft_state: "completed" as const,
        selected_completed_revision_id: "events-completed-1",
      },
      draft: {
        ...completedBase.draft,
        coverage: {
          kind: "event_intervals" as const,
          intervals: [{ start_us: 0, end_us: 3_000_000 }],
        },
      },
    };
    const corrected = referenceResponse(
      [eventItem({ review_state: "corrected" })],
      6,
      {
        state: {
          ...completed.state,
          draft_revision: 6,
          draft_state: "draft",
        },
        draft: {
          ...completed.draft,
          revision: 6,
          items: [eventItem({ review_state: "corrected" })],
          coverage: {
            kind: "event_intervals",
            intervals: [{ start_us: 0, end_us: 3_000_000 }],
          },
        },
      },
    );
    const published = referenceResponse(
      [eventItem({ review_state: "corrected" })],
      6,
      {
        state: {
          ...corrected.state,
          draft_state: "completed",
          selected_completed_revision_id: "events-completed-2",
        },
      },
    );
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method === "PUT") return response(corrected);
      if (init?.method === "POST") return response(published);
      return response(completed);
    });

    renderReviewed(fetchMock, 3_000_000);
    const publishButton = await screen.findByRole("button", {
      name: "Publish corrected reference",
    });
    expect(publishButton).toBeDisabled();
    expect(
      screen.getByText(
        "Reference is already complete; make a correction before publishing.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("operator-01"), {
      target: { value: "operator-1" },
    });
    fireEvent.change(screen.getByPlaceholderText("reviewer-01"), {
      target: { value: "reviewer-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Nudge later ." }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Publish corrected reference" }),
      ).not.toBeDisabled(),
    );
    expect(
      screen.queryByText(
        "Reference is already complete; make a correction before publishing.",
      ),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Publish corrected reference" }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
  });
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
