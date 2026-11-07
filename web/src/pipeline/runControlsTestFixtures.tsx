import type { PipelineWorkspaceStage } from "../api/pipelineContracts";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";

export function stage(
  key: PipelineWorkspaceStage["key"],
  overrides: Record<string, unknown> = {},
): PipelineWorkspaceStage {
  return {
    key,
    processor_key: key,
    processor_type: key,
    output_content_type: key,
    state: "empty",
    input_options: [],
    selection_revision: null,
    selected_generated: null,
    selected_completed_reference: null,
    runs: [],
    analyses: [],
    compatible_input_sets: [],
    can_run: true,
    run_blockers: [],
    comparable_run_ids: [],
    ...normalizeWorkspaceSelectionFixture(overrides),
  } as PipelineWorkspaceStage;
}

export function option(revisionId: string, displayLabel = revisionId) {
  return {
    revision_id: revisionId,
    node_id: `node-${revisionId}`,
    node_revision_id: `node-revision-${revisionId}`,
    is_current_head: true,
    content_type: "events" as const,
    origin: "processor" as const,
    completion_state: "complete" as const,
    coverage_state: "complete",
    display_label: displayLabel,
    content_sha256: "a".repeat(64),
    input_revision_ids: [],
    producer: {},
    coverage: {},
    created_at: "2026-09-06T00:00:00Z",
  };
}

export function runResponse(
  runId: string,
  status = "running",
  request: Record<string, unknown> = {},
  state: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    run_id: runId,
    recording_id: "recording-run-controls",
    processor_type: "event-detection",
    status,
    attempt: 1,
    request: {
      run_id: runId,
      input_revision_ids: [],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
      ...request,
    },
    state: {
      status,
      progress: { completed: 0, total: 1 },
      terminal_failure: null,
      ...state,
    },
  };
}

export function jobResponse(
  id: string,
  state: "queued" | "running" | "succeeded" | "failed" = "queued",
) {
  return {
    id,
    state,
    request: { processor_request: { run_id: id } },
    steps: [],
    failure: null,
  };
}
