import userEvent from "@testing-library/user-event";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { VisibleCardReviewWorkbench } from "./VisibleCardReviewWorkbench";
import * as fixtures from "./VisibleCardReviewWorkbenchFixtures";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import type { CalibrationRefinementResponse } from "../api/client";
const { calibrationRefinement, frame } = fixtures;

describe("VisibleCardReviewWorkbench", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("moves a virtual card by the full pointer distance in Rectified view", async () => {
    const onSceneChange = vi.fn();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSceneChange={onSceneChange}
      />,
    );
    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
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

    const card = screen.getByRole("button", {
      name: "Select virtual card card-1",
    });
    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    const scale = Math.min(100 / viewBox[2], 100 / viewBox[3]);
    const offsetX = (100 - viewBox[2] * scale) / 2;
    const offsetY = (100 - viewBox[3] * scale) / 2;
    const startClientX = offsetX + (50 - viewBox[0]) * scale;
    const startClientY = offsetY + (50 - viewBox[1]) * scale;
    fireEvent.pointerDown(card, {
      button: 0,
      clientX: startClientX,
      clientY: startClientY,
      pointerId: 1,
    });
    fireEvent.pointerMove(surface, {
      clientX: startClientX + 10,
      clientY: startClientY,
      pointerId: 1,
    });
    fireEvent.pointerMove(surface, {
      clientX: startClientX + 20,
      clientY: startClientY,
      pointerId: 1,
    });
    fireEvent.pointerUp(surface, { pointerId: 1 });

    await waitFor(() => expect(onSceneChange).toHaveBeenCalledTimes(1));
    expect(onSceneChange.mock.calls[0][0].scene.poses[0].center[0]).toBeCloseTo(
      50 + 20 / scale,
    );
  });

  it("moves virtual-card actions into the Timeline Rail", async () => {
    const onSceneChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSceneChange={onSceneChange}
      />,
    );

    const rotation = screen.getByRole("spinbutton", {
      name: "Rotation (degrees)",
    });
    expect(rotation).toBeDisabled();
    expect(screen.queryByRole("spinbutton", { name: /card-1/ })).toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    );
    expect(
      screen.getByRole("spinbutton", { name: "Rotation (degrees)" }),
    ).toBeEnabled();
    expect(
      within(
        screen.getByRole("group", { name: "Selection actions" }),
      ).getByRole("button", { name: "Accept card card-1 Click" }),
    ).toHaveAttribute("title", "Accept card card-1 (Click)");
    expect(
      screen.getByRole("button", { name: "Accept card card-1 Click" }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Add virtual card Click" }),
    );

    await waitFor(() => expect(onSceneChange).toHaveBeenCalledTimes(1));
    expect(onSceneChange.mock.calls[0][0].scene.poses).toHaveLength(2);
    expect(onSceneChange.mock.calls[0][1]).toContain("added");
  });

  it("uses the virtual-card keyboard nudge and keeps the card target explicit", async () => {
    const onSceneChange = vi.fn();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSceneChange={onSceneChange}
      />,
    );

    const card = screen.getByRole("button", {
      name: "Select virtual card card-1",
    });
    fireEvent.click(card);
    fireEvent.keyDown(card, { key: "ArrowRight" });

    await waitFor(() => expect(onSceneChange).toHaveBeenCalledTimes(1));
    expect(onSceneChange.mock.calls[0][0].scene.poses[0].center[0]).toBeCloseTo(
      50.025,
    );
    expect(
      screen.getByRole("button", { name: "Remove card card-1 Click" }),
    ).toBeDisabled();
  });

  it("rotates a selected virtual card with the keyboard shortcut", async () => {
    const onSceneChange = vi.fn();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onSceneChange={onSceneChange}
      />,
    );

    const card = screen.getByRole("button", {
      name: "Select virtual card card-1",
    });
    fireEvent.click(card);
    fireEvent.keyDown(card, { key: "r" });

    await waitFor(() => expect(onSceneChange).toHaveBeenCalledTimes(1));
    expect(onSceneChange.mock.calls[0][0].scene.poses[0].rotation_degrees).toBe(
      5,
    );
  });

  it("keeps card acceptance separate from frame actions", async () => {
    const onCardDecision = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        onCardDecision={onCardDecision}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Accept card card-1 Click" }),
    );

    expect(onCardDecision).toHaveBeenCalledWith("card-1", "accept");
    expect(screen.queryByRole("button", { name: "Accept frame" })).toBeNull();
  });

  it("shows convert-to-ignore actions after checking a proposal while editing virtual cards", async () => {
    const onToggleCandidateSelection = vi.fn();
    const onToolChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        selectedCandidateIds={[]}
        onToggleCandidateSelection={onToggleCandidateSelection}
        onToolChange={onToolChange}
        enabledEditTools={["visible_regions", "virtual_cards", "mapping"]}
        proposalSlot={null}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", {
        name: /Convert selection to ignore region/,
      }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 1 for ignore region",
      }),
    );

    expect(onToolChange).toHaveBeenCalledWith("visible_regions");
    expect(onToggleCandidateSelection).toHaveBeenCalledWith("suggestion-1");
    expect(
      screen.getByRole("button", { name: "Edit Visible regions" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps convert-to-ignore visible while proposals stay checked", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        selectedCandidateIds={["suggestion-1"]}
        initialPreferences={{
          activeTool: "virtual_cards",
          viewpoint: "rectified",
        }}
        enabledEditTools={["visible_regions", "virtual_cards", "mapping"]}
        proposalSlot={null}
      />,
    );

    expect(
      screen.getByRole("button", {
        name: /Convert selection to ignore region/,
      }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Add virtual card/ }),
    ).not.toBeInTheDocument();
    const markedRow = screen
      .getByRole("checkbox", {
        name: "Select proposal 1 for ignore region",
      })
      .closest("[data-marked-for-ignore]");
    expect(markedRow).toHaveAttribute("data-marked-for-ignore", "true");
    expect(
      within(markedRow as HTMLElement).getByText("Marked for ignore"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Select for ignore region"),
    ).not.toBeInTheDocument();
  });

  it("marks proposals already covered by an ignore region", () => {
    const coveredFrame: EditableFrame = {
      ...frame,
      outcome: {
        ...frame.outcome,
        candidates: [
          {
            card_id: "covered-1",
            geometry: {
              kind: "detector-region/v1",
              visible_region: {
                polygons: [
                  [
                    { x: 5, y: 5 },
                    { x: 15, y: 5 },
                    { x: 15, y: 15 },
                    { x: 5, y: 15 },
                  ],
                ],
              },
            },
            normalization: {},
            side: "unknown",
          },
          {
            card_id: "open-1",
            geometry: {
              kind: "detector-box/v1",
              box_2d: { x_min: 80, y_min: 80, x_max: 95, y_max: 95 },
            },
            normalization: {},
            side: "unknown",
          },
        ],
      },
    };
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={coveredFrame}
        readOnly={false}
        enabledEditTools={["visible_regions", "virtual_cards", "mapping"]}
        proposalSlot={null}
      />,
    );

    const ignoredRow = screen
      .getByText("Already ignored")
      .closest("[data-already-ignored]");
    expect(ignoredRow).toHaveAttribute("data-already-ignored", "true");
    expect(
      screen.getByRole("checkbox", {
        name: "Select proposal 1 for ignore region",
      }),
    ).toBeDisabled();
    expect(
      within(
        screen.getByRole("button", { name: "Select proposal 2" }),
      ).getByText("Detector suggestion"),
    ).toBeInTheDocument();
  });

  it("keeps mapping anchor actions and gestures on the shared surface", async () => {
    const onAnchorCommand = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
        onAnchorCommand={onAnchorCommand}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Adjust calibration anchor 1 for anchor-1",
      }),
    );
    expect(
      screen.getByRole("button", { name: "Accept anchor Click" }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Accept anchor Click" }),
    );

    expect(onAnchorCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: "set_state",
        state: "accepted",
        anchor_id: "anchor-1",
        expected_draft_revision: 0,
        sequence: 1,
      }),
    );
    expect(
      screen.queryByRole("button", { name: "Apply mapping Click" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a dragged anchor in place while its save is pending", async () => {
    let finishSave!: (saved: boolean) => void;
    const onAnchorCommand = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          finishSave = resolve;
        }),
    );
    const { rerender } = render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
        onAnchorCommand={onAnchorCommand}
      />,
    );
    const surface = screen.getByRole("img", {
      name: /visible-card workbench/i,
    });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 100,
      bottom: 100,
      width: 100,
      height: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    const handle = screen.getByRole("button", {
      name: "Adjust calibration anchor 1 for anchor-1",
    });
    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    const scale = Math.min(100 / viewBox[2], 100 / viewBox[3]);
    const offsetX = (100 - viewBox[2] * scale) / 2;
    const offsetY = (100 - viewBox[3] * scale) / 2;
    const clientPoint = (x: number, y: number) => ({
      clientX: offsetX + (x - viewBox[0]) * scale,
      clientY: offsetY + (y - viewBox[1]) * scale,
    });
    fireEvent.pointerDown(handle, { pointerId: 1, ...clientPoint(40, 40) });
    fireEvent.pointerMove(surface, { pointerId: 1, ...clientPoint(45, 45) });
    fireEvent.pointerUp(surface, { pointerId: 1 });
    expect(onAnchorCommand).toHaveBeenCalledTimes(1);
    expect(handle).toHaveAttribute("cx", "45");
    const savedRefinement = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ quadrilateral: number[][] }> };
    };
    savedRefinement.draft.anchors[0].quadrilateral[0] = [45, 45];
    rerender(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={savedRefinement}
        onAnchorCommand={onAnchorCommand}
      />,
    );
    await act(async () => finishSave(true));
    expect(handle).toHaveAttribute("cx", "45");
  });

  it("keeps mapping anchors visible when navigating to a frame without a card scene", async () => {
    const noSceneFrame = structuredClone(frame);
    noSceneFrame.itemId = "event-2";
    noSceneFrame.outcome.event_id = "event-2";
    noSceneFrame.outcome.card_scene = undefined;
    const nextFrameRefinement = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ source_frame_id: string }> };
    };
    nextFrameRefinement.draft.anchors[0].source_frame_id = "event-2";
    const { rerender } = render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
      />,
    );

    rerender(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={noSceneFrame}
        readOnly={false}
        initialPreferences={{ activeTool: "visible_regions" }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={nextFrameRefinement}
      />,
    );

    expect(
      await screen.findByRole("button", {
        name: "Adjust calibration anchor 1 for anchor-1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Mapping diagnostics" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Edit Mapping diagnostics" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("starts the current mapping preview when mapping edit mode opens", async () => {
    const onStartMappingPreview = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        enabledEditTools={["mapping"]}
        onStartMappingPreview={onStartMappingPreview}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Edit Mapping diagnostics" }),
    );

    expect(onStartMappingPreview).toHaveBeenCalledOnce();
    expect(document.querySelector('[data-projection="current"]')).toBeNull();
    expect(
      screen.queryByRole("button", { name: /mapped card corner/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Adjust calibration anchor/i }),
    ).toBeNull();
  });

  it("offers corner edits for rejected calibration candidates", () => {
    const onAnchorCommand = vi.fn();
    const ineligibleRefinement = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ eligible?: boolean }> };
    };
    ineligibleRefinement.draft.anchors[0].eligible = false;
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={ineligibleRefinement}
        onAnchorCommand={onAnchorCommand}
      />,
    );

    expect(
      screen.getAllByRole("button", { name: /Adjust calibration anchor/i }),
    ).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /Adjust mapped card corner/i }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Adjust calibration anchor 1 for anchor-1",
      }),
    );
    fireEvent.change(screen.getByLabelText("Anchor corner 1 X"), {
      target: { value: "41" },
    });
    fireEvent.keyDown(screen.getByLabelText("Anchor corner 1 Y"), {
      key: "Enter",
    });
    expect(onAnchorCommand).toHaveBeenCalledWith(
      expect.objectContaining({ operation: "set_corners", moved_corner: 0 }),
    );
  });

  it("keeps calibration anchor controls in the rectified view without duplicate card corners", () => {
    const onAnchorCommand = vi.fn();
    const rectifiedFrame = structuredClone(frame);
    rectifiedFrame.outcome.card_scene!.projection.table_to_image_homography = [
      [1, 0, 10],
      [0, 1, 5],
      [0, 0, 1],
    ];
    const rectifiedCalibration = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ quadrilateral: number[][] }> };
    };
    rectifiedCalibration.draft.anchors[0].quadrilateral = [
      [50, 45],
      [70, 45],
      [70, 65],
      [50, 65],
    ];
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={rectifiedFrame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping", "virtual_cards"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={rectifiedCalibration}
        onAnchorCommand={onAnchorCommand}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Select calibration anchor 1 for/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", {
        name: /^Adjust calibration anchor \d for anchor-1$/,
      }),
    ).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /Adjust mapped card corner/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Select anchor corner/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Use .* anchor constraint/ }),
    ).not.toBeInTheDocument();

    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
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

    const handle = screen.getByRole("button", {
      name: "Adjust calibration anchor 1 for anchor-1",
    });
    expect(Number(handle.getAttribute("r"))).toBeGreaterThanOrEqual(0.4);
    const layerGroups = Array.from(
      surface.querySelectorAll("[data-workbench-layer]"),
    );
    expect(layerGroups.at(-1)).toHaveAttribute(
      "data-workbench-layer",
      "mapping",
    );
    expect(layerGroups.at(-1)?.lastElementChild).toHaveAttribute(
      "data-anchor-id",
      "anchor-1",
    );
    expect(
      surface.querySelector('[data-workbench-layer="virtual_cards"]'),
    ).toHaveAttribute("pointer-events", "none");
    fireEvent.click(handle);
    expect(screen.getByLabelText("Anchor corner 1 X")).toBeInTheDocument();
  });
});
