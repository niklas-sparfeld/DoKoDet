import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import * as fixtures from "./PipelineVisibleCardEditorFixtures";
const {
  FRAME_IDENTITY,
  IGNORE_REGION,
  ITEM_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  jsonResponse,
  reference,
  referenceWithIgnoreRegion,
  referenceWithTwoCandidates,
  referenceWithTwoFrames,
} = fixtures;

describe("PipelineVisibleCardEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("draws, reshapes, and deletes an ignore region with dedicated operations", async () => {
    const responses = [
      referenceWithTwoCandidates(),
      referenceWithIgnoreRegion([]),
      referenceWithIgnoreRegion([]),
      reference(),
    ];
    let putCount = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        const response =
          responses[Math.min(putCount + 1, responses.length - 1)];
        putCount += 1;
        return Promise.resolve(jsonResponse(response));
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

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("button", {
        name: "Draw ignore region in shared workbench",
      }),
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
    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 80 });
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const createBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(createBody.operations[0]).toMatchObject({
      operation: "create_ignore_region",
      item_id: ITEM_ID,
      region: { reason: "untidy_stack" },
    });

    await user.click(
      screen.getByRole("button", { name: "Select ignore region 1" }),
    );
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    const regionCanvas = screen.getByRole("img", {
      name: "0 visible-card proposals and 1 ignore region",
    });
    vi.spyOn(regionCanvas, "getBoundingClientRect").mockReturnValue({
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
    fireEvent.pointerDown(point, { clientX: 10, clientY: 10, pointerId: 5 });
    fireEvent.pointerMove(regionCanvas, {
      clientX: 20,
      clientY: 20,
      pointerId: 5,
    });
    fireEvent.pointerUp(regionCanvas, { pointerId: 5 });
    await waitFor(() => expect(putCount).toBe(2));
    const replaceBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[1]?.[1]?.body,
      ),
    );
    expect(replaceBody.operations[0]).toMatchObject({
      operation: "replace_ignore_region",
      item_id: ITEM_ID,
      region_id: IGNORE_REGION.region_id,
    });

    await user.click(screen.getByRole("button", { name: "Delete selection" }));
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(3),
    );
    const deleteBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[2]?.[1]?.body,
      ),
    );
    expect(deleteBody.operations[0]).toMatchObject({
      operation: "delete_ignore_region",
      item_id: ITEM_ID,
      region_id: IGNORE_REGION.region_id,
    });
  });

  it("saves points added after an ignore region reaches three points", async () => {
    let putCount = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putCount += 1;
        return Promise.resolve(jsonResponse(referenceWithIgnoreRegion([])));
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

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("button", {
        name: "Draw ignore region in shared workbench",
      }),
    );
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

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 80 });
    await waitFor(() => expect(putCount).toBe(1));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Ignore region created.",
      ),
    );
    const createBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[0]?.[1]?.body,
      ),
    );

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 80 });
    await waitFor(() => expect(putCount).toBe(2));

    const replaceBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[1]?.[1]?.body,
      ),
    );
    expect(replaceBody.operations[0]).toMatchObject({
      operation: "replace_ignore_region",
      item_id: ITEM_ID,
      region_id: createBody.operations[0].region.region_id,
      region: {
        geometry: {
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
    });
  });

  it("adds a second polygon and saves its completed points", async () => {
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

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Add polygon" }));
    expect(
      screen.getByRole("button", {
        name: "Select polygon 2 for proposal 1",
      }),
    ).toHaveAttribute("aria-pressed", "true");

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
    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 20 });
    fireEvent.pointerDown(canvas, { clientX: 40, clientY: 20 });
    fireEvent.pointerDown(canvas, { clientX: 30, clientY: 40 });

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
        .polygons,
    ).toHaveLength(2);
  });

  it("commits the clamped edge point and ends the drag when the pointer leaves", async () => {
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

    await screen.findByRole("img", { name: /visible-card proposal/ });
    const controls = screen.getByRole("group", {
      name: "Frame navigation",
    });
    expect(
      within(controls).getByRole("button", { name: "Previous frame" }),
    ).toBeInTheDocument();
    expect(
      within(controls).getByRole("button", { name: "Previous frame" }),
    ).toHaveAttribute("aria-keyshortcuts", "ArrowLeft");
    expect(
      screen.getByRole("button", { name: "Accept frame" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add visible card" }),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select proposal 1" }));
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
    fireEvent.pointerLeave(canvas, {
      clientX: -10,
      clientY: 50,
      pointerId: 3,
    });
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    fireEvent.pointerMove(canvas, {
      clientX: 80,
      clientY: 80,
      pointerId: 3,
    });
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 800, 800",
      }),
    ).not.toBeInTheDocument();
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
    expect(
      requestBody.operations[0].item.candidates[0].geometry.visible_region
        .polygons[0][0],
    ).toEqual({ x: 0, y: 500 });
    expect(requestBody.operations[0].item.candidates[0].geometry.kind).toBe(
      "reviewed-visible-region/v1",
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();
  });

  it("selects a point without moving it until a real drag starts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(reference()))),
    );

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
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
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

    fireEvent.pointerDown(point, {
      clientX: 12,
      clientY: 12,
      pointerId: 9,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 14,
      clientY: 14,
      pointerId: 9,
    });
    fireEvent.pointerUp(canvas, { pointerId: 9 });

    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 140, 140",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps edit mode active and selects a card per frame", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        Promise.resolve(
          jsonResponse(
            init?.method === "PUT" ? reference() : referenceWithTwoFrames(),
          ),
        ),
      ),
    );

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
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    const visibleRegionTool = screen.getByRole("button", {
      name: "Edit Visible regions",
    });
    expect(visibleRegionTool).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowRight" });

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Polygon 1, point 1 at 100, 100",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(visibleRegionTool).toHaveAttribute("aria-pressed", "true");

    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();
  });

  it("ends edit mode when changing the frame state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        Promise.resolve(
          jsonResponse(
            init?.method === "PUT" ? reference("accepted") : reference(),
          ),
        ),
      ),
    );

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
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Accept frame" }));

    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();
  });

  it("closes polygon editing with Escape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(reference()))),
    );

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
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).not.toBeInTheDocument();
  });
});
