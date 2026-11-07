import type { components, paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type PipelineWorkspace = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline"]["get"]["responses"][200]
>;
export type PipelineWorkspaceStage = PipelineWorkspace["stages"][number];
export type PipelineRun = PipelineWorkspaceStage["runs"][number];
export type PipelineCompatibleInputSet =
  PipelineWorkspaceStage["compatible_input_sets"][number];
export type PipelineWorkspaceProcessorInputReference =
  PipelineCompatibleInputSet["input_node_refs"][number];
export type PipelineStageKey = PipelineWorkspaceStage["key"];
export type PipelineSelectableContentType = Exclude<
  PipelineStageKey,
  "round_analyses"
>;
export type PipelineSelectionUpdateRequest = {
  expected_revision: number;
  selected_generated: { node_id: string; revision_id: string } | null;
};
export type PipelineSelection = {
  revision: number;
  recording_id: string;
  content_type: PipelineSelectableContentType;
  selected_generated: { node_id: string; revision_id: string } | null;
  selected_completed_reference: { node_id: string; revision_id: string } | null;
  updated_at: string;
};
export type PipelineSelectionResponse = {
  recording_id: string;
  selection: PipelineSelection;
};
export type PipelineRunStartRequest = {
  request: {
    run_id: string;
    input_node_refs?: PipelineWorkspaceProcessorInputReference[];
    input_node_ref?: {
      node_id: string;
      revision_id: string;
      revision_policy: "current_head" | "historical";
    };
    crop_input_kind?:
      | "gemini_polygon"
      | "rfdetr_segment"
      | "proposed_virtual_cards"
      | "reviewed_virtual_card"
      | "reviewed_visible_card";
    processor_type?: string;
    implementation?: { name: string; version: string };
    model?: Record<string, unknown> | null;
    configuration?: Record<string, unknown>;
    extraction_policy?: Record<string, unknown>;
    crop_policy?: Record<string, unknown> | null;
  };
};
export type PipelineRunResponse = {
  run_id: string;
  job_id: string | null;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
};
export type AutomatedPipelineRun = {
  schema_version: "automated-pipeline-run/v1";
  run_id: string;
  job_id?: string | null;
  recording_id: string;
  status:
    "accepted" | "queued" | "running" | "complete" | "failed" | "cancelled";
  failure: Record<string, unknown> | null;
  request: Record<string, unknown>;
  stages: Array<{
    name: string;
    status:
      "pending" | "queued" | "running" | "complete" | "partial" | "failed";
    run_id: string | null;
    child_job_id?: string | null;
    input_revision_ids: string[];
    output_revision_ids: string[];
    failure: Record<string, unknown> | null;
  }>;
};
export type AutomatedPipelineStartRequest = {
  idempotency_key: string;
  session_id: string;
  round_context: {
    game_id: string;
    round_id: string;
    active_players: string[];
    dealer: string;
    first_trick_leader: string;
  };
  rules_version: "v1";
  search: {
    max_missing_plays: number;
    max_hypotheses: number;
    max_search_nodes: number;
  };
  stage_requests: Record<
    string,
    { configuration: Record<string, unknown>; [key: string]: unknown }
  >;
};
export type PipelineProposalRunResponse = PipelineRunResponse;
export type PipelineProposalResultResponse = PipelineRunResponse & {
  revisions: Array<{
    manifest: Record<string, unknown>;
    content: Record<string, unknown>;
  }>;
};
export type PipelineComparisonRequest =
  components["schemas"]["PipelineComparisonRequest"];
export type PipelineComparisonResponse = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/comparisons"]["post"]["responses"][200]
>;
export type FrameReviewPageResponse = JsonResponse<
  paths["/api/frame-reviews/0096-M4"]["get"]["responses"][200]
>;
export type FrameReviewWorkflowResponse = JsonResponse<
  paths["/api/frame-reviews/0096-M4/items/{recording_id}/{item_id}/workflow"]["put"]["responses"][200]
>;
export type PipelineEventResult = {
  run_id: string;
  recording_id: string;
  processor_type: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  revisions: Array<{
    manifest: Record<string, unknown>;
    content: {
      schema_version?: string;
      events?: Array<Record<string, unknown>>;
    };
  }>;
};
export type PipelineVisibleCardResult = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/visible-cards/{run_id}/result"]["get"]["responses"][200]
>;
export type PipelineVisualIdentityResult = JsonResponse<
  paths["/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}/result"]["get"]["responses"][200]
>;
