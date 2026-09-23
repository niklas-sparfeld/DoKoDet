import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { VisibleCardReviewWorkbench } from "./VisibleCardReviewWorkbench";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import type { PoseSceneEnvelope } from "./PoseBasedVisibleCardScene";
import type { CalibrationRefinementResponse } from "../api/client";

const scene: PoseSceneEnvelope = {
  schema_version: "reviewed-card-scene-editor/v1",
  scene: {
    schema_version: "reviewed-card-scene/v1",
    source_frame_id: "event-1",
    source_frame_width: 100,
    source_frame_height: 100,
    calibration_revision_id: "calibration-1",
    calibration_digest: "calibration-digest",
    poses: [
      {
        schema_version: "card-pose/v1",
        card_id: "card-1",
        center: [50, 50],
        rotation_degrees: 0,
        source_suggestion_id: "suggestion-1",
        fit_diagnostics_digest: null,
      },
    ],
    stacking_order: {
      schema_version: "card-stacking-order/v1",
      card_ids: ["card-1"],
      uncertain_edges: [],
      contradictions: [],
    },
    derivation_recipe_version: "test/v1",
    scene_digest: "scene-digest",
  },
  initialized_scene: {
    schema_version: "reviewed-card-scene/v1",
    source_frame_id: "event-1",
    source_frame_width: 100,
    source_frame_height: 100,
    calibration_revision_id: "calibration-1",
    calibration_digest: "calibration-digest",
    poses: [
      {
        schema_version: "card-pose/v1",
        card_id: "card-1",
        center: [50, 50],
        rotation_degrees: 0,
        source_suggestion_id: "suggestion-1",
        fit_diagnostics_digest: null,
      },
    ],
    stacking_order: {
      schema_version: "card-stacking-order/v1",
      card_ids: ["card-1"],
      uncertain_edges: [],
      contradictions: [],
    },
    derivation_recipe_version: "test/v1",
    scene_digest: "scene-digest",
  },
  projection: {
    table_to_image_homography: [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ],
    card_short_size: 10,
    card_long_size: 20,
  },
  card_review_states: [
    {
      card_id: "card-1",
      source: "proposal",
      proposal_id: "proposal-1",
      state: "pending",
    },
  ],
  completion_state: "pending",
  completion_reason: null,
};

const frame: EditableFrame = {
  itemId: "event-1",
  baseItemId: null,
  reviewState: "pending",
  outcome: {
    event_id: "event-1",
    frame_identity: {
      requested_time_us: 400_000,
      frame_index: 4,
      presentation_timestamp_us: 400_000,
      width: 100,
      height: 100,
      image_sha256: "a".repeat(64),
    },
    status: "detected",
    candidates: [
      {
        card_id: "suggestion-1",
        geometry: {
          kind: "detector-box/v1",
          box_2d: { x_min: 30, y_min: 30, x_max: 70, y_max: 70 },
        },
        normalization: {},
        side: "unknown",
      },
    ],
    ignored_regions: [
      {
        region_id: "ignore-1",
        geometry: {
          kind: "reviewed-ignore-region/v1",
          polygons: [
            [
              { x: 5, y: 5 },
              { x: 15, y: 5 },
              { x: 15, y: 15 },
              { x: 5, y: 15 },
            ],
          ],
        },
        normalization: { width: 100, height: 100, policy_id: "test" },
        reason: "untidy_stack",
        source_candidates: [],
      },
    ],
    card_scene: scene,
    error: null,
  },
};

const calibrationRefinement = {
  schema_version: "table-plane-calibration-refinement/v1",
  recording_id: "recording-1",
  proposal_revision_id: "proposal-1",
  draft: {
    draft_id: "draft-1",
    revision: 0,
    anchors: [
      {
        anchor_id: "anchor-1",
        card_id: "suggestion-1",
        source_frame_id: "event-1",
        eligible: true,
        state: "candidate",
        quadrilateral: [
          [40, 40],
          [60, 40],
          [60, 60],
          [40, 60],
        ],
      },
    ],
    commands: [],
  },
  preview: {
    status: "pass",
    candidate_calibration: {
      table_to_image: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
      card_short_size: 10,
      card_long_size: 20,
    },
    accepted_anchor_count: 0,
    rejected_candidate_count: 0,
    fit_residual: 0,
    held_out_alignment_change_px: 0,
    changed_frame_ids: [],
    changed_card_ids: [],
    max_source_pixel_displacement: 0,
    most_affected_frame_ids: [],
    gates: [],
    failure: null,
    preview_digest: "preview-digest",
  },
  anchor_contributions: [],
} as CalibrationRefinementResponse;

describe("VisibleCardReviewWorkbench", () => {
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

  it("keeps proposal sidebar previews and details in their separate grid columns", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly
        proposalSlot={null}
      />,
    );

    expect(
      screen.getByRole("img", { name: "Proposal 1 crop preview" }),
    ).toBeInTheDocument();
    const proposal = screen.getByRole("button", { name: "Select proposal 1" });
    expect(proposal.querySelector("svg")).toBeInTheDocument();
    expect(
      within(proposal).getByText("Detector suggestion"),
    ).toBeInTheDocument();
    expect(within(proposal).getByText("Unknown")).toBeInTheDocument();
    expect(within(proposal).getByText("Box")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select ignore region 1" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Select polygon/ }),
    ).not.toBeInTheDocument();
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

  it("keeps unavailable layers visible with a reason", () => {
    const noCalibrationFrame = structuredClone(frame);
    noCalibrationFrame.outcome.card_scene = undefined;
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
    expect(virtualCards).toBeDisabled();
    expect(virtualCards).toHaveAttribute(
      "title",
      "A valid table-plane calibration is required for this control.",
    );
    expect(
      screen.getByRole("button", { name: "Mapping diagnostics" }),
    ).toBeDisabled();
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

  it("puts frame decisions in the Timeline Rail", async () => {
    const onAccept = vi.fn();
    const onMarkEmpty = vi.fn();
    const onMarkUnusable = vi.fn();
    const user = userEvent.setup();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        frameDecision={{
          accepted: false,
          canAccept: true,
          acceptDisabledReason: "Frame changes must be saved first.",
          onAccept,
          onMarkEmpty,
          onMarkUnusable,
        }}
      />,
    );

    const frameDecision = screen.getByRole("group", {
      name: "Frame decision",
    });
    expect(
      within(
        screen.getByRole("toolbar", { name: "Workbench command bar" }),
      ).queryByRole("group", { name: "Frame decision" }),
    ).toBeNull();
    expect(
      within(frameDecision).getByRole("button", { name: "Accept frame" }),
    ).toBeEnabled();
    expect(
      within(frameDecision).getByRole("button", { name: "Mark empty" }),
    ).toBeEnabled();
    expect(
      within(frameDecision).getByRole("button", { name: "Mark unusable" }),
    ).toBeEnabled();

    await user.click(
      within(frameDecision).getByRole("button", { name: "Accept frame" }),
    );
    await user.click(
      within(frameDecision).getByRole("button", { name: "Mark empty" }),
    );
    await user.click(
      within(frameDecision).getByRole("button", { name: "Mark unusable" }),
    );

    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onMarkEmpty).toHaveBeenCalledTimes(1);
    expect(onMarkUnusable).toHaveBeenCalledTimes(1);
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
        mappingCanApply
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
      screen.getByRole("button", { name: "Apply mapping Click" }),
    ).toBeEnabled();
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
    expect(
      screen.queryByRole("button", { name: /mapped card corner/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Adjust calibration anchor/i }),
    ).toBeNull();
  });

  it("does not offer corner edits for ineligible calibration anchors", () => {
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
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Adjust calibration anchor/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Adjust mapped card corner/i }),
    ).toBeNull();
  });

  it("moves the actual calibration anchor corner in the rectified view", () => {
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
      screen.getAllByRole("button", { name: /Adjust mapped card corner/i }),
    ).toHaveLength(4);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Adjust mapped card corner 4 for card-1",
      }),
    );
    expect(screen.getByLabelText("Anchor corner 4 X")).toHaveValue(50);
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
    expect(
      surface.querySelector('[data-workbench-layer="virtual_cards"]'),
    ).toHaveAttribute("pointer-events", "none");
    fireEvent.click(handle);
    expect(screen.getByLabelText("Anchor corner 1 X")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Adjust calibration anchor 4 for anchor-1",
      }),
    );
    expect(screen.getByLabelText("Anchor corner 4 X")).toHaveValue(50);
    fireEvent.click(handle);
    const viewBox = surface.getAttribute("viewBox")!.split(" ").map(Number);
    const scale = Math.min(100 / viewBox[2], 100 / viewBox[3]);
    const offsetX = (100 - viewBox[2] * scale) / 2;
    const offsetY = (100 - viewBox[3] * scale) / 2;
    const clientPoint = (x: number, y: number) => ({
      clientX: offsetX + (x - viewBox[0]) * scale,
      clientY: offsetY + (y - viewBox[1]) * scale,
    });
    const mappedHandle = screen.getByRole("button", {
      name: "Adjust mapped card corner 1 for card-1",
    });
    fireEvent.pointerDown(mappedHandle, {
      pointerId: 1,
      ...clientPoint(45, 40),
    });
    expect(screen.getByLabelText("Anchor corner 1 X")).toBeInTheDocument();
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      ...clientPoint(47, 47),
    });
    fireEvent.pointerUp(surface, { pointerId: 1 });

    expect(onAnchorCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: "set_corners",
        moved_corner: 0,
        constraint: null,
        corners: [
          [52, 52],
          [70, 45],
          [70, 65],
          [50, 65],
        ],
      }),
    );
  });

  it("shrinks mapping strokes and corner handles with zoom", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
          viewpoint: "rectified",
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
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

    const handle = screen.getByRole("button", {
      name: "Adjust calibration anchor 1 for anchor-1",
    });
    const projection = surface.querySelector(
      '[data-projection="current"] polygon',
    );
    expect(projection).not.toBeNull();
    const initialRadius = Number(handle.getAttribute("r"));
    const initialStrokeWidth = Number(projection?.getAttribute("stroke-width"));
    expect(handle).toHaveAttribute("opacity", "0.5");
    expect(projection).toHaveAttribute("opacity", "0.5");

    fireEvent.wheel(surface, { deltaY: -240 });

    expect(Number(handle.getAttribute("r"))).toBe(initialRadius / 2);
    expect(Number(projection?.getAttribute("stroke-width"))).toBe(
      initialStrokeWidth / 2,
    );
  });

  it("shows numbered stack badges and lets the sidebar reorder cards", async () => {
    const multiCardFrame = structuredClone(frame);
    const cardScene = multiCardFrame.outcome.card_scene!;
    const secondCard = {
      ...cardScene.scene.poses[0],
      card_id: "card-2",
      center: [60, 60] as [number, number],
    };
    cardScene.scene.poses[0].center = [15, 15];
    cardScene.projection.table_to_image_homography = [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0.01, 1],
    ];
    cardScene.scene.poses.push(secondCard);
    cardScene.scene.stacking_order.card_ids.push(secondCard.card_id);
    cardScene.initialized_scene.poses.push(secondCard);
    cardScene.initialized_scene.stacking_order.card_ids.push(
      secondCard.card_id,
    );
    const onSceneChange = vi.fn();

    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={multiCardFrame}
        readOnly={false}
        onSceneChange={onSceneChange}
        proposalSlot={null}
      />,
    );

    await userEvent.setup().click(
      screen.getByRole("button", { name: "Edit Virtual cards" }),
    );
    expect(
      screen.queryByText("Stack order · Front to back"),
    ).not.toBeInTheDocument();
    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    expect(
      surface.querySelector('[data-stacking-badge-id="card-1"]'),
    ).toHaveAttribute("data-stacking-index", "0");
    expect(
      surface.querySelector('[data-stacking-badge-id="card-2"]'),
    ).toHaveAttribute("data-stacking-index", "1");

    await userEvent.setup().click(
      screen.getByRole("button", {
        name: "Viewpoint: Rectified. Switch to Camera",
      }),
    );
    const cameraSurface = screen.getByRole("img", {
      name: /1 visible-card proposal/,
    });
    const badgeRadii = Array.from(
      cameraSurface.querySelectorAll("[data-card-stacking-badges] circle"),
      (badge) => Number(badge.getAttribute("r")),
    );
    expect(badgeRadii).toHaveLength(2);
    expect(badgeRadii[0]).toBeGreaterThan(4);
    expect(badgeRadii[0]).toBe(badgeRadii[1]);

    const stackOrder = screen.getByRole("region", { name: "Stack order" });
    const firstRow = stackOrder.querySelector(
      '[data-card-id="card-1"][data-stacking-index="0"]',
    );
    const secondRow = stackOrder.querySelector(
      '[data-card-id="card-2"][data-stacking-index="1"]',
    );
    const values = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      getData: (type: string) => values.get(type) ?? "",
      setData: (type: string, value: string) => values.set(type, value),
    };
    fireEvent.dragStart(firstRow!, { dataTransfer });
    fireEvent.drop(secondRow!, { dataTransfer });

    await waitFor(() => expect(onSceneChange).toHaveBeenCalled());
    expect(
      onSceneChange.mock.calls.at(-1)?.[0].scene.stacking_order.card_ids,
    ).toEqual(["card-2", "card-1"]);
  });
});
