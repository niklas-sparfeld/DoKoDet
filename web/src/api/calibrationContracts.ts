import type { paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type PipelineCalibration = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}"]["get"]["responses"][200]
>;

export type CalibrationRefinementResponse = {
  schema_version: "table-plane-calibration-refinement/v1";
  recording_id: string;
  proposal_revision_id: string;
  /** False when the draft has quick anchor-fit data but no recording-wide preview. */
  preview_complete?: boolean;
  draft: Record<string, unknown>;
  preview: {
    status: "pass" | "blocked";
    candidate_calibration: {
      table_to_image: number[][];
      card_short_size: number;
      card_long_size: number;
    } | null;
    accepted_anchor_count: number;
    rejected_candidate_count: number;
    fit_residual: number;
    held_out_alignment_change_px: number;
    changed_frame_ids: string[];
    changed_card_ids: string[];
    max_source_pixel_displacement: number;
    most_affected_frame_ids: string[];
    gates: Array<{
      gate_id: string;
      passed: boolean;
      observed: number;
      threshold: number;
      message: string;
    }>;
    failure: { code: string; message: string; action: string } | null;
    preview_digest: string;
  };
  anchor_contributions: Array<Record<string, unknown>>;
};
export type CalibrationRefinementApplyResponse = {
  schema_version: "table-plane-calibration-refinement/v1";
  action: "applied";
  recording_id: string;
  source_proposal_revision_id: string;
  proposal_revision_id: string;
  calibration_revision_id: string;
  receipt: Record<string, unknown>;
  visible_card_node_ref: { node_id: string; revision_id: string };
  detection_set_ref: {
    set_id: string;
    version: string;
    content_sha256: string;
  };
};
