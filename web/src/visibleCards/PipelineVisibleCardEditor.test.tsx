import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";

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
const DETECTOR_CANDIDATE = {
  card_id: "run-card-1",
  geometry: {
    kind: "visible-region/v1",
    visible_region: {
      polygons: [
        [
          { x: 100, y: 100 },
          { x: 800, y: 100 },
          { x: 800, y: 800 },
          { x: 100, y: 800 },
        ],
      ],
    },
  },
  normalization: {
    width: 100,
    height: 100,
    policy_id: "full-frame-0-1000/v1",
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

  it("sends one complete set_frame_review command when a polygon drag ends", async () => {
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
  });

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
    expect(
      screen.getByText(/Each frame needs an explicit/),
    ).toBeInTheDocument();
  });
});
