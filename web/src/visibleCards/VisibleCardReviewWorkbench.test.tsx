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
        card_id: "card-1",
        source_frame_id: "event-1",
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

  it("puts visible-region actions and editor points in the shared surface", async () => {
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

    expect(
      screen.getByRole("button", { name: "Add visible card" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /Polygon 1, point 1/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add visible card" }));
    expect(onAction).toHaveBeenCalledWith("add_visible_card", null);
  });

  it("converts rectified pointer coordinates back to source coordinates", () => {
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
    fireEvent.pointerDown(surface, {
      clientX: ((50 - viewBox[0]) / viewBox[2]) * 100,
      clientY: ((50 - viewBox[1]) / viewBox[3]) * 100,
    });
    expect(onCanvasPointerDown).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        x: expect.closeTo(500),
        y: expect.closeTo(500),
      }),
    );
  });

  it("moves virtual-card actions into the shared command bar", async () => {
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

    await user.click(
      screen.getByRole("button", { name: "Select virtual card card-1" }),
    );
    expect(
      screen.getByRole("button", { name: "Accept card card-1" }),
    ).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Add virtual card" }));

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
      screen.getByRole("button", { name: "Remove card card-1" }),
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
      screen.getByRole("button", { name: "Accept card card-1" }),
    );

    expect(onCardDecision).toHaveBeenCalledWith("card-1", "accept");
    expect(screen.queryByRole("button", { name: "Accept frame" })).toBeNull();
  });

  it("keeps frame decisions in the command bar", async () => {
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
    expect(screen.getByRole("button", { name: "Accept anchor" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Accept anchor" }));

    expect(onAnchorCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: "set_state",
        state: "accepted",
        anchor_id: "anchor-1",
        expected_draft_revision: 0,
        sequence: 1,
      }),
    );
    expect(screen.getByRole("button", { name: "Apply mapping" })).toBeEnabled();
  });
});
