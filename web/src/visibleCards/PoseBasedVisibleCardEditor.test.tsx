import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PoseBasedVisibleCardEditor } from "./PoseBasedVisibleCardEditor";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import type { PoseSceneEnvelope } from "./PoseBasedVisibleCardScene";

const DIGEST = "a".repeat(64);

function scene(): PoseSceneEnvelope {
  const poses = [
    {
      schema_version: "card-pose/v1" as const,
      card_id: "card-a",
      center: [0, 0] as [number, number],
      rotation_degrees: 0,
      source_suggestion_id: "suggestion-a",
      fit_diagnostics_digest: DIGEST,
    },
    {
      schema_version: "card-pose/v1" as const,
      card_id: "card-b",
      center: [2, 0] as [number, number],
      rotation_degrees: 0,
      source_suggestion_id: "suggestion-b",
      fit_diagnostics_digest: DIGEST,
    },
  ];
  const makeScene = () => ({
    schema_version: "reviewed-card-scene/v1" as const,
    source_frame_id: "frame-1",
    source_frame_width: 100,
    source_frame_height: 80,
    calibration_revision_id: "calibration-1",
    calibration_digest: DIGEST,
    poses: poses.map((pose) => ({
      ...pose,
      center: [...pose.center] as [number, number],
    })),
    stacking_order: {
      schema_version: "card-stacking-order/v1" as const,
      card_ids: ["card-a", "card-b"],
      uncertain_edges: [],
      contradictions: [],
    },
    derivation_recipe_version: "card-plane-derived-regions/v1",
    scene_digest: DIGEST,
  });
  return {
    schema_version: "reviewed-card-scene-editor/v1",
    scene: makeScene(),
    initialized_scene: makeScene(),
    projection: {
      table_to_image_homography: [
        [20, 0, 50],
        [0, 20, 40],
        [0, 0, 1],
      ],
      card_short_size: 1,
      card_long_size: 1.5,
    },
  };
}

function frame(): EditableFrame {
  return {
    itemId: "event-1",
    baseItemId: null,
    reviewState: "pending",
    outcome: {
      event_id: "event-1",
      frame_identity: {
        requested_time_us: 100,
        frame_index: 1,
        presentation_timestamp_us: 100,
        width: 100,
        height: 80,
        image_sha256: DIGEST,
      },
      status: "detected",
      candidates: [],
      ignored_regions: [],
      error: null,
    },
  };
}

describe("PoseBasedVisibleCardEditor", () => {
  it("saves one scene command when a standard card is added", async () => {
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
      />,
    );

    expect(
      screen.getByRole("application", { name: "Rectified virtual table" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Add standard-size card" }),
    );

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0].scene.poses).toHaveLength(3);
    expect(onChange.mock.calls[0][1]).toContain("added");
  });

  it("uses the same editor action for keyboard nudges", async () => {
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
      />,
    );

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Virtual table card card-a" }),
      {
        key: "ArrowRight",
      },
    );

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0].scene.poses[0].center[0]).toBe(0.025);
  });
});
