import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import * as fixtures from "./PipelineVisibleCardEditorFixtures";
const {
  FRAME_IDENTITY,
  ITEM_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  jsonResponse,
  reference,
  referenceWithTwoCandidates,
} = fixtures;

describe("PipelineVisibleCardEditor pile workflow", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("draws and publishes a pile footprint in the source frame", async () => {
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
    await user.click(screen.getByRole("button", { name: /Draw pile region/ }));
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
