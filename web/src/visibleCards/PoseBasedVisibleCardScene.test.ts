import {
  applyPoseSceneAction,
  cardPolygon,
  createCalibrationAnchorCommand,
  createCalibrationAnchorStateCommand,
  moveAnchorCorner,
  withCalibrationAnchorCommandDigest,
  nextManualPoseId,
  projectImagePointToTable,
  projectTablePoint,
  readPoseScene,
  type PoseSceneEnvelope,
} from "./PoseBasedVisibleCardScene";

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
      rotation_degrees: 15,
      source_suggestion_id: "suggestion-b",
      fit_diagnostics_digest: DIGEST,
    },
  ];
  const makeScene = () => ({
    schema_version: "reviewed-card-scene/v1" as const,
    source_frame_id: "frame-1",
    source_frame_width: 1000,
    source_frame_height: 800,
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
        [100, 0, 500],
        [0, 100, 400],
        [0, 0, 1],
      ],
      card_short_size: 1,
      card_long_size: 1.5,
    },
  };
}

describe("PoseBasedVisibleCardScene", () => {
  it("reads the frozen scene envelope and projects fixed card corners", () => {
    const current = scene();
    expect(readPoseScene(current)).toEqual(current);
    expect(nextManualPoseId(current.scene)).toBe("manual-card-1");
    expect(cardPolygon(current.scene.poses[0], current.projection)).toEqual([
      [-0.5, -0.75],
      [0.5, -0.75],
      [0.5, 0.75],
      [-0.5, 0.75],
    ]);
    expect(
      projectTablePoint([1, 2], current.projection.table_to_image_homography),
    ).toEqual([600, 600]);
  });

  it("edits pose centers and order without changing immutable suggestion lineage", () => {
    const current = scene();
    const moved = applyPoseSceneAction(current, {
      type: "move",
      cardId: "card-a",
      center: [3, 4],
    });
    const reordered = applyPoseSceneAction(moved, {
      type: "bring_forward",
      cardId: "card-b",
    });
    expect(reordered.scene.poses[0].center).toEqual([3, 4]);
    expect(reordered.scene.poses[0].source_suggestion_id).toBe("suggestion-a");
    expect(reordered.scene.stacking_order.card_ids).toEqual([
      "card-b",
      "card-a",
    ]);
  });

  it("adds and removes standard cards and restores the initialized scene", () => {
    const current = scene();
    const added = applyPoseSceneAction(current, {
      type: "add",
      cardId: "manual-card-1",
      center: [5, 5],
    });
    expect(added.scene.poses).toHaveLength(3);
    expect(added.scene.poses.at(-1)?.source_suggestion_id).toBeNull();
    const removed = applyPoseSceneAction(added, {
      type: "remove",
      cardId: "card-a",
    });
    expect(removed.scene.poses.map((pose) => pose.card_id)).toEqual([
      "card-b",
      "manual-card-1",
    ]);
    const restored = applyPoseSceneAction(removed, {
      type: "restore_initialized",
    });
    expect(restored.scene).toEqual(current.initialized_scene);
  });

  it("does not remove the last pose from a scene", () => {
    const current = scene();
    const oneCard = {
      ...current,
      scene: {
        ...current.scene,
        poses: [current.scene.poses[0]],
        stacking_order: {
          ...current.scene.stacking_order,
          card_ids: ["card-a"],
        },
      },
    };
    expect(
      applyPoseSceneAction(oneCard, { type: "remove", cardId: "card-a" }),
    ).toEqual(oneCard);
  });

  it("moves only the selected anchor corner without a geometric constraint", () => {
    const corners: [
      [number, number],
      [number, number],
      [number, number],
      [number, number],
    ] = [
      [0, 0],
      [1.5, 0],
      [1.5, 1],
      [0, 1],
    ];
    expect(moveAnchorCorner(corners, 0, [-1.5, -1])).toEqual([
      [-1.5, -1],
      [1.5, 0],
      [1.5, 1],
      [0, 1],
    ]);
  });

  it("adds the canonical digest required by calibration refinement updates", async () => {
    const command = createCalibrationAnchorCommand({
      command_id: "anchor-command-frame-1-1",
      sequence: 1,
      expected_draft_revision: 0,
      anchor_id: "anchor-frame-1-card-1",
      moved_corner: 0,
      corners: [
        [-1, -1.5],
        [1, -1.5],
        [1, 1.5],
        [-1, 1.5],
      ],
      operator_id: "operator",
    });

    await expect(withCalibrationAnchorCommandDigest(command)).resolves.toEqual(
      expect.objectContaining({
        command_digest:
          "03709b841584e670c47865b1fb92770bb71362212509a3d97ba9a22f49eec5b1",
      }),
    );
  });

  it("digests an anchor decision with null corners", async () => {
    const command = createCalibrationAnchorStateCommand({
      command_id: "anchor-command-frame-1-2",
      sequence: 2,
      expected_draft_revision: 1,
      anchor_id: "anchor-frame-1-card-1",
      state: "accepted",
      operator_id: "operator",
    });
    await expect(withCalibrationAnchorCommandDigest(command)).resolves.toEqual(
      expect.objectContaining({
        corners: null,
        command_digest:
          "e812bb06f7a7a2c19faa28f564e128cade8558958f61d0fe658c0e3cb0b4f7bb",
      }),
    );
  });

  it("maps source points back through the preserved homography", () => {
    const homography = [
      [100, 0, 500],
      [0, 100, 400],
      [0, 0, 1],
    ];
    expect(projectImagePointToTable([600, 600], homography)).toEqual([1, 2]);
  });
});
