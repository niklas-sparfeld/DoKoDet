import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import type { Candidate } from "./PipelineVisibleCardTypes";

const RECORDING_ID = "visible-pipeline-recording";
const RUN_ID = "visible-run-1";
const REVISION_ID = "visible-revision-1";
const ITEM_ID = "event-1";
const SECOND_ITEM_ID = "event-2";
const FRAME_IDENTITY = {
  schema_version: "exact-event/v1",
  source_video_sha256: "a".repeat(64),
  requested_time_us: 400_000,
  frame_index: 4,
  presentation_timestamp_us: 400_000,
  width: 100,
  height: 100,
  decoder_version: "fixture-decoder/v1",
  transform_version: "fixture-frame/v1",
  output_encoding: "jpeg",
  content_type: "image/jpeg",
  image_sha256: "b".repeat(64),
  policy: "exact-event/v1",
};
const DETECTOR_CANDIDATE: Candidate = {
  card_id: "run-card-1",
  geometry: {
    kind: "detector-box/v1",
    box_2d: { x_min: 100, y_min: 100, x_max: 800, y_max: 800 },
  },
  normalization: {
    width: 100,
    height: 100,
    policy_id: "full-frame-0-1000/v1",
  },
};

const SEGMENTED_GEOMETRY_WITH_DERIVED_BOX: Candidate["geometry"] = {
  kind: "detector-box/v1",
  box_2d: { x_min: 100, y_min: 100, x_max: 820, y_max: 820 },
  visible_region: {
    polygons: [
      [
        { x: 140, y: 180 },
        { x: 760, y: 120 },
        { x: 820, y: 760 },
        { x: 200, y: 820 },
      ],
    ],
  },
};

function generatedResult() {
  return {
    run_id: RUN_ID,
    recording_id: RECORDING_ID,
    processor_type: "visible-card-detection",
    status: "complete",
    attempt: 1,
    request: {},
    state: {},
    revisions: [
      {
        manifest: { revision_id: REVISION_ID },
        content: {
          outcomes: [
            {
              event_id: ITEM_ID,
              frame_identity: FRAME_IDENTITY,
              status: "detected",
              candidates: [DETECTOR_CANDIDATE],
              error: null,
            },
          ],
        },
      },
    ],
  };
}

function generatedResultWithTwoFrames() {
  const result = generatedResult();
  result.revisions[0].content.outcomes.push({
    event_id: SECOND_ITEM_ID,
    frame_identity: {
      ...FRAME_IDENTITY,
      requested_time_us: 800_000,
      frame_index: 8,
      presentation_timestamp_us: 800_000,
      image_sha256: "c".repeat(64),
    },
    status: "detected",
    candidates: [
      {
        ...DETECTOR_CANDIDATE,
        card_id: "run-card-2",
      },
    ],
    error: null,
  });
  return result;
}

function reference(state: "pending" | "accepted" | "corrected" = "pending") {
  return {
    recording_id: RECORDING_ID,
    content_type: "visible_cards",
    state: {
      recording_id: RECORDING_ID,
      content_type: "visible_cards",
      draft_revision: state === "pending" ? 0 : 1,
      draft_state: "draft",
      source_revision_id: REVISION_ID,
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: RECORDING_ID,
      content_type: "visible_cards",
      revision: state === "pending" ? 0 : 1,
      source_revision_id: REVISION_ID,
      items: [
        {
          item_id: ITEM_ID,
          base_item_id: null,
          review_state: state,
          item: {
            event_id: ITEM_ID,
            frame_identity: FRAME_IDENTITY,
            status: "detected",
            candidates: [
              state === "corrected"
                ? {
                    ...DETECTOR_CANDIDATE,
                    geometry: {
                      kind: "reviewed-visible-region/v1",
                      visible_region: {
                        polygons: [
                          [
                            { x: 100, y: 100 },
                            { x: 820, y: 100 },
                            { x: 820, y: 820 },
                            { x: 100, y: 820 },
                          ],
                        ],
                      },
                    },
                  }
                : DETECTOR_CANDIDATE,
            ],
            error: null,
          },
        },
      ],
      coverage: null,
      impact: [],
      updated_at: "2026-09-06T00:00:00Z",
    },
  };
}

function referenceWithSegmentedGeometry() {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: item.item.candidates.map((candidate) => ({
            ...candidate,
            geometry: SEGMENTED_GEOMETRY_WITH_DERIVED_BOX,
          })),
        },
      })),
    },
  };
}

function referenceWithPolygon(polygon: { x: number; y: number }[]) {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: item.item.candidates.map((candidate) => ({
            ...candidate,
            geometry: {
              kind: "reviewed-visible-region/v1" as const,
              visible_region: { polygons: [polygon] },
            },
          })),
        },
      })),
    },
  };
}

function emptyReference() {
  const current = reference();
  return {
    ...current,
    state: {
      ...current.state,
      source_revision_id: null,
    },
    draft: {
      ...current.draft,
      source_revision_id: null,
      items: [],
    },
  };
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PipelineVisibleCardEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("keeps generated detector output read-only and uses the derived frame URL", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(generatedResult())),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    const railItems = vi.fn();

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByAltText("Selected visible-card source frame"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("video")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Visible-card suggestions" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Generated detector output is immutable/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Source revision/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Resolved-frame timeline"),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        expect.objectContaining({
          itemId: ITEM_ID,
          proposalCount: 1,
          timeUs: FRAME_IDENTITY.requested_time_us,
        }),
      ]),
    );
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
    expect(fetchImplementation.mock.calls[0]?.[0]).toContain(
      "/pipeline/visible-cards/visible-run-1/result",
    );
  });

  it("renders each segmented visible-region polygon as its own overlay", async () => {
    const result = generatedResult();
    result.revisions[0].content.outcomes[0].candidates = [
      {
        ...DETECTOR_CANDIDATE,
        geometry: {
          kind: "visible-region/v1",
          visible_region: {
            polygons: [
              [
                { x: 100, y: 100 },
                { x: 400, y: 100 },
                { x: 400, y: 800 },
                { x: 100, y: 800 },
              ],
              [
                { x: 600, y: 200 },
                { x: 900, y: 200 },
                { x: 900, y: 700 },
                { x: 600, y: 700 },
              ],
            ],
          },
        },
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(result))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    const canvas = await screen.findByRole("img", {
      name: "1 visible-card proposal",
    });
    expect(canvas.querySelectorAll("polygon")).toHaveLength(2);
  });

  it("keeps the generated frame and proposals visible after entering review before start", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/pipeline/visible-cards/") &&
      String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse({ message: "not found" }, 404)),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        displayedRevisionId={null}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    expect(
      await screen.findByAltText("Selected visible-card source frame"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Start visible-card review" }),
    ).toBeInTheDocument();
    const proposal = screen.getByRole("button", {
      name: "Select proposal 1",
    });
    expect(proposal).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(proposal);
    expect(proposal).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Box")).toBeInTheDocument();
  });

  it("shows generated proposals when an existing maintained reference is empty", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(reference()));
      }
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(emptyReference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    expect(
      await screen.findByAltText("Selected visible-card source frame"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Start visible-card review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select proposal 1" }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(screen.getByRole("button", { name: "Start review" }));

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      { operation: "rebase", source_revision_id: REVISION_ID },
    ]);
    expect(
      await screen.findByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
  });

  it("edits stored polygons after starting review when derived box data is also present", async () => {
    const segmentedReference = referenceWithSegmentedGeometry();
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(segmentedReference));
      }
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(emptyReference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: "Start visible-card review" });
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(screen.getByRole("button", { name: "Start review" }));
    await screen.findByRole("button", { name: "Edit" });
    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 140, 180",
      }),
    ).toBeInTheDocument();
    const polygons = screen
      .getByRole("img", { name: "1 visible-card proposal" })
      .querySelectorAll("polygon");
    expect(polygons).toHaveLength(2);
    expect(polygons[0]).toHaveAttribute("stroke-width", "1.25");
    expect(polygons[1]).toHaveAttribute("stroke-width", "1.25");
    expect(polygons[1]).toHaveAttribute("stroke-dasharray", "4 3");
    expect(screen.getByText("Polygon")).toBeInTheDocument();
  });

  it("saves a polygon drag without leaving edit mode", async () => {
    const responses = [reference(), reference("corrected")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(responses[1]));
      }
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByAltText("Selected visible-card source frame");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(point, { clientX: 10, clientY: 10, pointerId: 3 });
    expect(point).toHaveAttribute("fill", "#ffffff");
    expect(point).toHaveAttribute("stroke", "#ffd24f");
    expect(point).toHaveAttribute("r", "1");
    fireEvent.pointerMove(canvas, { clientX: 15, clientY: 20, pointerId: 3 });
    fireEvent.pointerUp(canvas, { pointerId: 3 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toHaveLength(1);
    expect(requestBody.operations[0]).toMatchObject({
      operation: "set_frame_review",
      item_id: ITEM_ID,
      item: {
        event_id: ITEM_ID,
        frame_identity: FRAME_IDENTITY,
        status: "detected",
      },
    });
    expect(requestBody.operations[0].item.candidates[0].geometry.kind).toBe(
      "reviewed-visible-region/v1",
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 150, 200",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close editor" }),
    ).toBeInTheDocument();
  });

  it("inserts a clicked point between the endpoints of the nearest polygon edge", async () => {
    const responses = [
      referenceWithPolygon([
        { x: 100, y: 100 },
        { x: 900, y: 100 },
        { x: 900, y: 200 },
        { x: 100, y: 800 },
      ]),
      reference("corrected"),
    ];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT")
        return Promise.resolve(jsonResponse(responses[1]));
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByAltText("Selected visible-card source frame");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 15 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(
      requestBody.operations[0].item.candidates[0].geometry.visible_region
        .polygons[0],
    ).toEqual([
      { x: 100, y: 100 },
      { x: 500, y: 150 },
      { x: 900, y: 100 },
      { x: 900, y: 200 },
      { x: 100, y: 800 },
    ]);
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 2 at 500, 150",
      }),
    ).toBeInTheDocument();
  });

  it.each(["Backspace", "Delete"])(
    "removes the selected polygon point with %s",
    async (key) => {
      const responses = [reference(), reference("corrected")];
      const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
        if (init?.method === "PUT")
          return Promise.resolve(jsonResponse(responses[1]));
        return Promise.resolve(jsonResponse(responses[0]));
      });
      vi.stubGlobal("fetch", fetchImplementation);

      render(
        <PipelineVisibleCardEditor
          recordingId={RECORDING_ID}
          durationUs={1_000_000}
          generatedRevisionId={REVISION_ID}
          generatedRunId={RUN_ID}
          view="reviewed"
        />,
      );

      await screen.findByAltText("Selected visible-card source frame");
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Edit" }));
      const point = screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      });
      fireEvent.pointerDown(point, { pointerId: 3 });
      fireEvent.keyDown(point, { key });

      await waitFor(() =>
        expect(
          fetchImplementation.mock.calls.filter(
            ([, init]) => init?.method === "PUT",
          ),
        ).toHaveLength(1),
      );
      const requestBody = JSON.parse(
        String(
          fetchImplementation.mock.calls.find(
            ([, init]) => init?.method === "PUT",
          )?.[1]?.body,
        ),
      );
      expect(
        requestBody.operations[0].item.candidates[0].geometry.visible_region
          .polygons[0],
      ).toEqual([
        { x: 800, y: 100 },
        { x: 800, y: 800 },
        { x: 100, y: 800 },
      ]);
      expect(
        screen.getByRole("button", { name: "Close editor" }),
      ).toBeInTheDocument();
    },
  );

  it("selects the requested generated frame and reports both rail items", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(generatedResultWithTwoFrames())),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    const railItems = vi.fn();

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        selectionItemId={SECOND_ITEM_ID}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByAltText("Selected visible-card source frame"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        expect.objectContaining({ itemId: ITEM_ID, timeUs: 400_000 }),
        expect.objectContaining({ itemId: SECOND_ITEM_ID, timeUs: 800_000 }),
      ]),
    );
  });

  it("cycles through the current frame proposals with the up and down arrows", async () => {
    const result = generatedResult();
    result.revisions[0].content.outcomes[0].candidates.push({
      ...DETECTOR_CANDIDATE,
      card_id: "run-card-2",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(result))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    await screen.findByAltText("Selected visible-card source frame");
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${ITEM_ID}`),
    );
    fireEvent.keyDown(window, { key: "ArrowDown" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select proposal 1" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    fireEvent.keyDown(window, { key: "ArrowDown" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select proposal 2" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    fireEvent.keyDown(window, { key: "ArrowUp" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select proposal 1" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("restores generated suggestions as a frame that still needs acceptance", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT")
        return Promise.resolve(jsonResponse(reference()));
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(reference("corrected")));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", {
        name: "Restore generated suggestions",
      }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      {
        operation: "restore_frame_suggestions",
        item_id: ITEM_ID,
        item: expect.objectContaining({
          event_id: ITEM_ID,
          candidates: [DETECTOR_CANDIDATE],
        }),
      },
    ]);
  });

  it("toggles an accepted frame back to unreviewed", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === "PUT" ? reference() : reference("accepted"),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Mark unreviewed" }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      { operation: "set_frame_unreviewed", item_id: ITEM_ID },
    ]);
    expect(screen.getAllByText(/Unreviewed/)).not.toHaveLength(0);
  });

  it("retries a transient draft save and keeps the review command intact", async () => {
    let putAttempts = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putAttempts += 1;
        if (putAttempts === 1) {
          return Promise.resolve(
            jsonResponse({ message: "temporary outage" }, 503),
          );
        }
        return Promise.resolve(jsonResponse(reference("accepted")));
      }
      return Promise.resolve(jsonResponse(reference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );
    await screen.findByAltText("Selected visible-card source frame");
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Reviewed empty frame" }),
    );

    await waitFor(
      () => {
        expect(putAttempts).toBe(2);
      },
      { timeout: 3_000 },
    );
    expect(
      fetchImplementation.mock.calls.filter(([input]) =>
        String(input).includes("/pipeline/references/"),
      ),
    ).toHaveLength(3);
  });

  it("records reviewed empty coverage and keeps completion blocked until a frame is decided", async () => {
    const responses = [reference(), reference("accepted")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(init?.method === "PUT" ? responses[1] : responses[0]),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );
    await screen.findByAltText("Selected visible-card source frame");
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Reviewed empty frame" }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations[0]).toEqual({
      operation: "set_frame_empty",
      item_id: ITEM_ID,
    });
    expect(screen.getByText(/Each frame must be accepted/)).toBeInTheDocument();
  });
});
