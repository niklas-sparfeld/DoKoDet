import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { VisibleCardReviewWorkbench } from "./VisibleCardReviewWorkbench";
import * as fixtures from "./VisibleCardReviewWorkbenchFixtures";
const { frame } = fixtures;

describe("VisibleCardReviewWorkbench", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders one stable command bar for generated and maintained frames", () => {
    for (const readOnly of [true, false]) {
      const { unmount } = render(
        <VisibleCardReviewWorkbench
          recordingId="recording-1"
          frame={frame}
          readOnly={readOnly}
        />,
      );
      expect(
        screen.getAllByRole("toolbar", { name: "Workbench command bar" }),
      ).toHaveLength(1);
      unmount();
    }
  });

  it("draws the fitted rounded outline instead of the detector polygon", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        calibrationFitOutlines={[
          {
            candidateId: "suggestion-1",
            points: [
              { x: 10, y: 10 },
              { x: 20, y: 10 },
              { x: 25, y: 15 },
              { x: 20, y: 20 },
              { x: 10, y: 20 },
              { x: 5, y: 15 },
            ],
            status: "fit",
            reason: null,
            confidence: 0.9,
            qualityScore: 0.8,
            medianDistancePx: 1,
            p90DistancePx: 2,
            maximumDistancePx: 3,
          },
        ]}
      />,
    );

    expect(
      document.querySelector("[data-calibration-fit-outline] polygon"),
    ).toHaveAttribute("data-geometry", "fitted");
    expect(
      document.querySelector("[data-calibration-fit-outline] polygon"),
    ).toHaveAttribute("points", "10,10 20,10 25,15 20,20 10,20 5,15");
  });

  it("renders enabled layers in the frozen order and keeps edit controls read-only", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
      />,
    );

    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    expect(
      [...surface.querySelectorAll("[data-workbench-layer]")].map((layer) =>
        layer.getAttribute("data-workbench-layer"),
      ),
    ).toEqual(["ignore_regions", "suggestions", "virtual_cards"]);
    expect(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    ).toBeDisabled();
  });

  it("switches to Camera with one viewpoint button and preserves selection", async () => {
    const onSelectionChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Select virtual card card-1",
      }),
    );
    expect(onSelectionChange).toHaveBeenLastCalledWith({
      type: "virtual_card",
      id: "card-1",
    });

    await user.click(
      screen.getByRole("button", {
        name: "Viewpoint: Rectified. Switch to Camera",
      }),
    );
    expect(
      screen.getByRole("img", { name: "1 visible-card proposal" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    ).toBeInTheDocument();
  });

  it("clears a selected virtual card with Escape", async () => {
    const onSelectionChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    );
    expect(
      screen.getByRole("spinbutton", { name: "Rotation (degrees)" }),
    ).toBeEnabled();

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
      { key: "Escape" },
    );

    expect(onSelectionChange).toHaveBeenLastCalledWith(null);
    expect(
      screen.getByRole("spinbutton", { name: "Rotation (degrees)" }),
    ).toBeDisabled();
  });

  it("clears a selected virtual card when the frame background is clicked", async () => {
    const onSelectionChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    );
    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    await user.click(surface);

    expect(onSelectionChange).toHaveBeenLastCalledWith(null);
    expect(
      screen.getByRole("spinbutton", { name: "Rotation (degrees)" }),
    ).toBeDisabled();
  });

  it("renders the camera source inside the SVG so overlays share frame coordinates", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        initialPreferences={{
          viewpoint: "camera",
          activeTool: "visible_regions",
        }}
      />,
    );

    const surface = screen.getByRole("img", {
      name: "1 visible-card proposal",
    });
    expect(surface).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
    expect(surface.parentElement).toHaveStyle({
      "--workbench-frame-aspect-ratio": "100 / 100",
    });
    const background = surface.querySelector(
      '[data-workbench-background="camera"]',
    );
    expect(background).not.toBeNull();
    expect(background).toHaveAttribute("width", "100");
    expect(background).toHaveAttribute("height", "100");
    expect(background).toHaveAttribute("x", "0");
    expect(background).toHaveAttribute("y", "0");
    expect(background).toHaveAttribute("preserveAspectRatio", "none");
    expect(surface.parentElement?.querySelector("img")).toBeNull();
  });

  it("keeps unavailable layers clickable and opens prerequisite guidance", async () => {
    const noCalibrationFrame = structuredClone(frame);
    noCalibrationFrame.outcome.card_scene = undefined;
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={noCalibrationFrame}
        readOnly
      />,
    );

    const virtualCards = screen.getByRole("button", {
      name: "Virtual cards",
    });
    expect(virtualCards).toBeEnabled();
    expect(virtualCards).toHaveAttribute(
      "title",
      "A valid table-plane calibration is required for this control.",
    );
    const rectified = screen.getByRole("button", {
      name: "Viewpoint: Camera. Switch to Rectified",
    });
    expect(rectified).toBeEnabled();
    await user.click(rectified);
    expect(
      screen.getByRole("dialog", {
        name: "Rectified needs a table-plane calibration",
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close guidance" }));
    await user.click(virtualCards);
    expect(
      screen.getByRole("dialog", {
        name: "Virtual cards needs a table-plane calibration",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
  });

  it("focuses the matching view layer when switching editor modes", async () => {
    const user = userEvent.setup();
    const frameWithVisibleRegion = structuredClone(frame);
    frameWithVisibleRegion.outcome.candidates[0].geometry.visible_region = {
      polygons: [
        [
          { x: 30, y: 30 },
          { x: 70, y: 30 },
          { x: 70, y: 70 },
          { x: 30, y: 70 },
        ],
      ],
    };
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frameWithVisibleRegion}
        readOnly={false}
        enabledEditTools={["visible_regions", "virtual_cards", "mapping"]}
      />,
    );

    const showLayer = (name: string) =>
      screen.getByRole("button", { name: new RegExp(`^${name}$`) });
    await user.click(
      screen.getByRole("button", { name: "Edit Visible regions" }),
    );
    expect(showLayer("Visible regions")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(showLayer("Virtual cards")).toHaveAttribute("aria-pressed", "false");
    expect(showLayer("Mapping diagnostics")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    );
    expect(showLayer("Visible regions")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(showLayer("Virtual cards")).toHaveAttribute("aria-pressed", "true");
    expect(showLayer("Mapping diagnostics")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(
      screen.getByRole("button", { name: "Edit Mapping diagnostics" }),
    );
    expect(showLayer("Visible regions")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(showLayer("Virtual cards")).toHaveAttribute("aria-pressed", "false");
    expect(showLayer("Mapping diagnostics")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows source detector cards in every edit mode", async () => {
    const user = userEvent.setup();
    const virtualTableFrame = structuredClone(frame);
    virtualTableFrame.outcome.candidates = [];
    const detectedCandidate = structuredClone(frame.outcome.candidates[0]);
    detectedCandidate.geometry.visible_region = {
      polygons: [
        [
          { x: 30, y: 30 },
          { x: 70, y: 30 },
          { x: 70, y: 70 },
          { x: 30, y: 70 },
        ],
      ],
    };

    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={virtualTableFrame}
        detectedCandidates={[detectedCandidate]}
        readOnly={false}
        enabledEditTools={["visible_regions", "virtual_cards", "mapping"]}
        proposalSlot={null}
      />,
    );

    const expectDetectedCard = () => {
      expect(
        screen.getByRole("button", { name: "Select proposal 1" }),
      ).toBeInTheDocument();
    };

    expectDetectedCard();
    await user.click(
      screen.getByRole("button", { name: "Edit Visible regions" }),
    );
    expectDetectedCard();
    await user.click(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    );
    expectDetectedCard();
    await user.click(
      screen.getByRole("button", { name: "Edit Mapping diagnostics" }),
    );
    expectDetectedCard();
  });

  it("puts visible-region actions in the Timeline Rail and keeps editor points in the shared surface", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{ activeTool: "visible_regions" }}
        enabledEditTools={["visible_regions"]}
        editor={{
          frameItemId: frame.itemId,
          cardId: "suggestion-1",
          regionId: null,
          ignoreRegion: null,
          polygons: [
            [
              { x: 100, y: 100 },
              { x: 800, y: 100 },
              { x: 800, y: 800 },
            ],
          ],
          polygonIndex: 0,
          selectedPointIndex: null,
        }}
        onAction={onAction}
      />,
    );

    const commandBar = screen.getByRole("toolbar", {
      name: "Workbench command bar",
    });
    expect(
      within(commandBar).queryByRole("group", { name: "Selection actions" }),
    ).toBeNull();
    const selectionActions = screen.getByRole("group", {
      name: "Selection actions",
    });
    const addVisibleCard = within(selectionActions).getByRole("button", {
      name: "Add visible card N",
    });
    expect(addVisibleCard).toBeEnabled();
    expect(addVisibleCard).toHaveTextContent("＋");
    expect(addVisibleCard).toHaveAttribute("title", "Add visible card (N)");
    expect(
      screen.getByRole("button", { name: /Polygon 1, point 1/ }),
    ).toBeInTheDocument();
    await user.click(addVisibleCard);
    expect(onAction).toHaveBeenCalledWith("add_visible_card", null);
  });

  it("converts rectified pointer coordinates back to source coordinates", () => {
    const onCanvasPointerDown = vi.fn();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "visible_regions",
          viewpoint: "camera",
        }}
        enabledEditTools={["visible_regions"]}
        onCanvasPointerDown={onCanvasPointerDown}
      />,
    );
    const surface = screen.getByRole("img", {
      name: "1 visible-card proposal",
    });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
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
    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    const scale = Math.min(100 / viewBox[2], 100 / viewBox[3]);
    const offsetX = (100 - viewBox[2] * scale) / 2;
    const offsetY = (100 - viewBox[3] * scale) / 2;
    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 1,
      clientX: offsetX + (50 - viewBox[0]) * scale,
      clientY: offsetY + (50 - viewBox[1]) * scale,
    });
    fireEvent.pointerUp(surface, { pointerId: 1 });
    expect(onCanvasPointerDown).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        x: expect.closeTo(500),
        y: expect.closeTo(500),
      }),
    );
  });

  it("zooms the non-rectified camera view with the surface wheel", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        initialPreferences={{ viewpoint: "camera" }}
      />,
    );
    const surface = screen.getByRole("img", {
      name: "1 visible-card proposal",
    });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
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

    expect(surface.getAttribute("viewBox")).toBe("0 0 100 100");
    fireEvent.wheel(surface, { clientX: 50, clientY: 50, deltaY: -120 });

    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    expect(viewBox[2]).toBeLessThan(100);
    expect(viewBox[3]).toBeLessThan(100);
  });

  it("restores each viewpoint's zoom without leaking its coordinate-space pan", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
      />,
    );
    const rectifiedSurface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    vi.spyOn(rectifiedSurface, "getBoundingClientRect").mockReturnValue({
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

    const initialRectifiedViewBox = rectifiedSurface
      .getAttribute("viewBox")!
      .split(" ")
      .map(Number);
    fireEvent.wheel(rectifiedSurface, {
      clientX: 85,
      clientY: 15,
      deltaY: -120,
    });
    const zoomedRectifiedViewBox = rectifiedSurface
      .getAttribute("viewBox")!
      .split(" ")
      .map(Number);
    expect(zoomedRectifiedViewBox[2]).toBeLessThan(initialRectifiedViewBox[2]);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Viewpoint: Rectified. Switch to Camera",
      }),
    );
    const cameraSurface = screen.getByRole("img", {
      name: "1 visible-card proposal",
    });
    expect(cameraSurface.getAttribute("viewBox")).toBe("0 0 100 100");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Viewpoint: Camera. Switch to Rectified",
      }),
    );
    const restoredRectifiedSurface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    const restoredRectifiedViewBox = restoredRectifiedSurface
      .getAttribute("viewBox")!
      .split(" ")
      .map(Number);
    expect(restoredRectifiedViewBox[2]).toBeCloseTo(zoomedRectifiedViewBox[2]);
    expect(restoredRectifiedViewBox[3]).toBeCloseTo(zoomedRectifiedViewBox[3]);
  });

  it("pans the non-rectified camera view when dragged", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        initialPreferences={{ viewpoint: "camera" }}
      />,
    );
    const surface = screen.getByRole("img", {
      name: "1 visible-card proposal",
    });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
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

    fireEvent.pointerDown(surface, {
      button: 0,
      clientX: 50,
      clientY: 50,
      pointerId: 1,
    });
    fireEvent.pointerMove(surface, {
      clientX: 60,
      clientY: 50,
      pointerId: 1,
    });

    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    expect(viewBox[0]).toBe(-10);
    expect(viewBox[1]).toBe(0);
  });

  it.each(["visible_regions", "mapping"] as const)(
    "pans the camera view when the %s tool is active",
    (activeTool) => {
      const onCanvasPointerDown = vi.fn();
      const frameWithoutScene = structuredClone(frame);
      if (activeTool === "visible_regions") {
        frameWithoutScene.outcome.card_scene = undefined;
      }
      render(
        <VisibleCardReviewWorkbench
          recordingId="recording-1"
          frame={frameWithoutScene}
          readOnly={false}
          initialPreferences={{ activeTool, viewpoint: "camera" }}
          enabledEditTools={[activeTool]}
          onCanvasPointerDown={onCanvasPointerDown}
        />,
      );
      const surface = screen.getByRole("img", {
        name: "1 visible-card proposal",
      });
      vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
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

      fireEvent.pointerDown(surface, {
        button: 0,
        clientX: 50,
        clientY: 50,
        pointerId: 1,
      });
      fireEvent.pointerMove(surface, {
        clientX: 60,
        clientY: 50,
        pointerId: 1,
      });
      fireEvent.pointerUp(surface, { pointerId: 1 });

      const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
      expect(viewBox[0]).toBe(-10);
      expect(viewBox[1]).toBe(0);
      expect(onCanvasPointerDown).not.toHaveBeenCalled();
    },
  );

  it("keeps visible-region canvas clicks when the pointer does not drag", () => {
    const onCanvasPointerDown = vi.fn();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{ activeTool: "visible_regions" }}
        enabledEditTools={["visible_regions"]}
        onCanvasPointerDown={onCanvasPointerDown}
      />,
    );
    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });

    fireEvent.pointerDown(surface, {
      button: 0,
      clientX: 50,
      clientY: 50,
      pointerId: 1,
    });
    fireEvent.pointerUp(surface, { pointerId: 1 });

    expect(onCanvasPointerDown).toHaveBeenCalledTimes(1);
  });
});
