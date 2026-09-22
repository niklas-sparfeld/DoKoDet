import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";

import { VisibleCardReviewWorkbench } from "./VisibleCardReviewWorkbench";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import type { PoseSceneEnvelope } from "./PoseBasedVisibleCardScene";

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
});
