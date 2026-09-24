import type { EditableFrame } from "./PipelineVisibleCardTypes";
import type { PoseSceneEnvelope } from "./PoseBasedVisibleCardScene";
import type { CalibrationRefinementResponse } from "../api/client";

export const scene: PoseSceneEnvelope = {
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

export const frame: EditableFrame = {
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

export const calibrationRefinement = {
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
