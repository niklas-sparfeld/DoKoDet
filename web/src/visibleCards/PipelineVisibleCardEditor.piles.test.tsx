import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import * as fixtures from "./PipelineVisibleCardEditorFixtures";
import { scene } from "./VisibleCardReviewWorkbenchFixtures";
const {
  FRAME_IDENTITY,
  ITEM_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  SECOND_ITEM_ID,
  jsonResponse,
  reference,
  referenceWithTwoCandidates,
  referenceWithTwoFrames,
} = fixtures;

describe("PipelineVisibleCardEditor pile workflow", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("draws and publishes a pile footprint in the source frame", async () => {
    const value = referenceWithTwoCandidates();
    const item = value.draft.items[0]!.item as Record<string, unknown>;
    item.card_scene = scene;
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(value)),
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
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(screen.getByRole("button", { name: /Draw pile region/ }));
    expect(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    ).toHaveAttribute("aria-pressed", "true");
    const canvas = screen.getByRole("img", {
      name: "2 visible-card proposals",
    });
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
    for (const [x, y] of [
      [10, 10],
      [80, 10],
      [80, 80],
    ]) {
      fireEvent.pointerDown(canvas, { clientX: x, clientY: y });
      fireEvent.pointerUp(canvas);
    }
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(body.operations[0]).toMatchObject({
      operation: "create_pile_region",
      item_id: ITEM_ID,
      region: {
        geometry: {
          kind: "pile-region/v1",
          polygons: [
            [
              { x: 100, y: 100 },
              { x: 800, y: 100 },
              { x: 800, y: 800 },
            ],
          ],
        },
      },
    });
    expect(body.operations[0]).not.toHaveProperty("candidate_ids");
  });

  it("inserts and moves pile corners in Virtual Cards mode", async () => {
    const value = reference();
    const item = value.draft.items[0]!.item as Record<string, unknown>;
    item.card_scene = scene;
    item.pile_detection_status = "supported";
    item.pile_regions = [
      {
        pile_id: "pile-1",
        geometry: {
          kind: "pile-region/v1",
          polygons: [
            [
              { x: 100, y: 100 },
              { x: 900, y: 100 },
              { x: 900, y: 800 },
            ],
          ],
        },
        normalization: {
          width: FRAME_IDENTITY.width,
          height: FRAME_IDENTITY.height,
          policy_id: "full-frame-0-1000/v1",
        },
        source_candidates: [],
        grouped_candidates: [],
        grouped_card_states: [],
        grouped_scene_decision: null,
        origin: "model_prediction",
        confidence: 0.87,
        model_lineage: {
          provider: "local-rfdetr-segmentation",
          bundle_identity: { bundle_digest: "a".repeat(64) },
        },
      },
    ];
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(value)),
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

    await screen.findByRole("img", { name: /visible-card proposal/ });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Select pile region pile-1" }));
    expect(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    ).toHaveAttribute("aria-pressed", "true");
    const canvas = screen.getByRole("img", { name: /pile region/ });
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

    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 10 });
    fireEvent.pointerUp(canvas);

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(body.operations[0]).toMatchObject({
      operation: "replace_pile_region",
      pile_id: "pile-1",
      region: {
        geometry: {
          polygons: [
            [
              { x: 100, y: 100 },
              { x: 500, y: 100 },
              { x: 900, y: 100 },
              { x: 900, y: 800 },
            ],
          ],
        },
      },
    });

    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    fireEvent.pointerDown(point, {
      clientX: 10,
      clientY: 10,
      pointerId: 7,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 20,
      clientY: 20,
      pointerId: 7,
    });
    fireEvent.pointerUp(canvas, { pointerId: 7 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(2),
    );
    const moveBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[1]?.[1]?.body,
      ),
    );
    expect(moveBody.operations[0]).toMatchObject({
      operation: "replace_pile_region",
      pile_id: "pile-1",
      region: {
        geometry: {
          polygons: [
            [
              { x: 200, y: 200 },
              { x: 500, y: 100 },
              { x: 900, y: 100 },
              { x: 900, y: 800 },
            ],
          ],
        },
      },
    });
  });

  it("groups only explicitly selected card proposals into a pile", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(referenceWithTwoCandidates())),
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
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 1 for region action",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: /Group selected cards into pile/ }),
    );
    const canvas = screen.getByRole("img", {
      name: "2 visible-card proposals",
    });
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
    for (const [x, y] of [
      [10, 10],
      [80, 10],
      [80, 80],
    ]) {
      fireEvent.pointerDown(canvas, { clientX: x, clientY: y });
      fireEvent.pointerUp(canvas);
    }
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(body.operations[0]).toMatchObject({
      operation: "group_cards_into_pile",
      item_id: ITEM_ID,
      candidate_ids: ["run-card-1"],
      region: { geometry: { kind: "pile-region/v1" } },
    });
  });

  it("keeps deleted candidates removed when copying pile regions", async () => {
    const value = referenceWithTwoFrames();
    const source = value.draft.items[0]!;
    source.review_state = "accepted";
    const sourceItem = source.item as Record<string, unknown>;
    const sourcePile = {
      pile_id: "source-pile",
      geometry: {
        kind: "pile-region/v1",
        polygons: [
          [
            { x: 100, y: 100 },
            { x: 800, y: 100 },
            { x: 800, y: 800 },
          ],
        ],
      },
      normalization: {
        width: FRAME_IDENTITY.width,
        height: FRAME_IDENTITY.height,
        policy_id: "full-frame-0-1000/v1",
      },
      source_candidates: [],
      grouped_candidates: [],
      grouped_card_states: [],
      grouped_scene_decision: null,
      origin: "model_prediction",
      confidence: 0.87,
      model_lineage: {
        provider: "local-rfdetr-segmentation",
        bundle_identity: { bundle_digest: "a".repeat(64) },
      },
    };
    sourceItem.pile_detection_status = "supported";
    sourceItem.pile_regions = [sourcePile];
    const destination = value.draft.items[1]!;
    const destinationItem = destination.item as Record<string, unknown>;
    destinationItem.candidates = [];
    destinationItem.pile_detection_status = "supported";
    destinationItem.pile_regions = [
      {
        ...sourcePile,
        pile_id: "destination-pile",
        grouped_candidates: [fixtures.DETECTOR_CANDIDATE],
      },
    ];
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(value)),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        selectionItemId={SECOND_ITEM_ID}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(screen.getByRole("button", { name: "Next frame →" }));
    await user.click(
      screen.getByRole("button", {
        name: "Copy pile regions from earlier frames Click",
      }),
    );

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(
      body.operations.map(
        (operation: { operation: string }) => operation.operation,
      ),
    ).toEqual([
      "delete_pile_region",
      "set_frame_review",
      "set_frame_pending",
      "create_pile_region",
    ]);
    expect(body.operations[1].item.candidates).toEqual([]);
    expect(body.operations[1].item.pile_regions).toEqual([]);
  });

  it("accepts and completes pile-only frame coverage", async () => {
    const withPile = (state: "pending" | "accepted") => {
      const value = reference(state);
      const item = value.draft.items[0]!.item as Record<string, unknown>;
      item.candidates = [];
      item.pile_detection_status = "supported";
      item.pile_regions = [
        {
          pile_id: "pile-1",
          geometry: {
            kind: "pile-region/v1",
            polygons: [
              [
                { x: 100, y: 100 },
                { x: 800, y: 100 },
                { x: 800, y: 800 },
              ],
            ],
          },
          normalization: {
            width: FRAME_IDENTITY.width,
            height: FRAME_IDENTITY.height,
            policy_id: "full-frame-0-1000/v1",
          },
          source_candidates: [],
          grouped_candidates: [],
          grouped_card_states: [],
          grouped_scene_decision: null,
          origin: "model_prediction",
          confidence: 0.87,
          model_lineage: {
            provider: "local-rfdetr-segmentation",
            bundle_identity: { bundle_digest: "a".repeat(64) },
          },
        },
      ];
      return value;
    };
    const pending = withPile("pending");
    const accepted = withPile("accepted");
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(init?.method === "PUT" ? accepted : pending),
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
    expect(
      await screen.findByText("Supported by provider"),
    ).toBeInTheDocument();
    expect(
      document.querySelector('[data-pile-id="pile-1"]'),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(
      await screen.findByRole("textbox", { name: "Operator ID" }),
      "operator-1",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reviewer ID" }),
      "reviewer-1",
    );
    await user.click(
      await screen.findByRole("button", { name: "Accept frame" }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    await user.click(
      screen.getByRole("button", { name: "Complete reference" }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([input, init]) =>
            init?.method === "POST" && String(input).includes("complete"),
        ),
      ).toBe(true),
    );
    const completion = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([input, init]) =>
            init?.method === "POST" && String(input).includes("complete"),
        )?.[1]?.body,
      ),
    );
    expect(completion.coverage.frames).toEqual([
      expect.objectContaining({ decision: "piles" }),
    ]);
  });
});
