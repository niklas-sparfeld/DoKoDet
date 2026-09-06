import type {
  PipelineStageKey,
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/client";
import { PIPELINE_STAGE_KEYS } from "../pipeline/recordingWorkspacePresentation";

export const RECORDING_PIPELINE_FIXTURE_ID = "recording-presentation-fixture";
export const RECORDING_PIPELINE_FIXTURE_DURATION_US = 90_000_000;

type PipelineRun = PipelineWorkspaceStage["runs"][number];
type PipelineAnalysis = PipelineWorkspaceStage["analyses"][number];
type PipelineRevision = PipelineWorkspaceStage["input_options"][number];

export function pipelineStage(
  key: PipelineStageKey = "events",
  overrides: Partial<PipelineWorkspaceStage> = {},
): PipelineWorkspaceStage {
  return {
    key,
    processor_key: `${key}-processor`,
    processor_type: `${key}-processor`,
    output_content_type: key,
    has_maintained_reference: key !== "round_analyses",
    state: "video-only",
    input_options: [],
    selection_revision: null,
    selected_generated_revision_id: null,
    selected_completed_reference_revision_id: null,
    runs: [],
    analyses: [],
    compatible_input_sets: [],
    reference: null,
    can_run: true,
    run_blockers: [],
    can_review: false,
    review_blockers: [],
    comparable_run_ids: [],
    ...overrides,
  };
}

export function pipelineRun(
  runId = "run-events-1",
  overrides: Partial<PipelineRun> = {},
): PipelineRun {
  return {
    attempt: 1,
    completed_at: null,
    configuration: {},
    created_at: "2026-09-06T00:00:00Z",
    crop_policy: null,
    extraction_policy: {},
    failed_item_count: 0,
    failure: null,
    implementation: { name: "fixture", version: "1" },
    input_revision_ids: [],
    model: null,
    output_revision_ids: [],
    progress: { completed: 0, total: 0 },
    request: {},
    run_id: runId,
    started_at: null,
    state: { items: [] },
    status: "queued",
    updated_at: "2026-09-06T00:00:00Z",
    ...overrides,
  };
}

export function pipelineAnalysis(
  analysisId = "analysis-1",
  overrides: Partial<PipelineAnalysis> = {},
): PipelineAnalysis {
  return {
    analysis_id: analysisId,
    completed_at: null,
    created_at: "2026-09-06T00:00:00Z",
    failure: null,
    input_revision_ids: ["observations-1"],
    progress: { completed: 0, total: 1 },
    recording_id: RECORDING_PIPELINE_FIXTURE_ID,
    request: {},
    round_id: "round-1",
    session_id: "session-1",
    started_at: null,
    state: "queued",
    ...overrides,
  };
}

export function pipelineRevision(
  revisionId = "events-generated-1",
  overrides: Partial<PipelineRevision> = {},
): PipelineRevision {
  return {
    revision_id: revisionId,
    content_type: "events",
    origin: "processor",
    completion_state: "complete",
    coverage_state: "full-recording",
    display_label: "Generated events",
    content_sha256: "b".repeat(64),
    input_revision_ids: [],
    producer: {},
    coverage: {},
    created_at: "2026-09-06T00:00:00Z",
    ...overrides,
  };
}

export function pipelineWorkspace({
  recordingId = RECORDING_PIPELINE_FIXTURE_ID,
  video = {},
  stageOverrides = {},
  diagnostics = [],
}: {
  recordingId?: string;
  video?: Partial<PipelineWorkspace["video"]>;
  stageOverrides?: Partial<
    Record<PipelineStageKey, Partial<PipelineWorkspaceStage>>
  >;
  diagnostics?: PipelineWorkspace["diagnostics"];
} = {}): PipelineWorkspace {
  return {
    schema_version: "pipeline-workspace/v1",
    recording_id: recordingId,
    video: {
      schema_version: "recording-video/v1",
      recording_id: recordingId,
      relative_path: `recordings/${recordingId}/video.mp4`,
      video_sha256: "a".repeat(64),
      byte_length: 10,
      duration_us: RECORDING_PIPELINE_FIXTURE_DURATION_US,
      ...video,
    },
    stages: PIPELINE_STAGE_KEYS.map((key) =>
      pipelineStage(key, stageOverrides[key]),
    ),
    diagnostics,
  };
}

export function recordingPipelinePresentationFixture(
  state:
    | "video-only"
    | "empty"
    | "generated-only"
    | "draft"
    | "affected"
    | "failed"
    | "complete",
): PipelineWorkspace {
  const generated = pipelineRevision();
  const generatedRun = pipelineRun("run-events-1", {
    status: state === "failed" ? "failed" : "complete",
    output_revision_ids: state === "failed" ? [] : [generated.revision_id],
    progress: { completed: 2, total: 2 },
    failure:
      state === "failed"
        ? { code: "fixture_failure", message: "The fixture run failed." }
        : null,
    state: {
      items: [
        {
          item_id: "event-1",
          status: state === "failed" ? "failed" : "succeeded",
          result: {
            event_type: "card_played",
            start_us: 1_000_000,
            end_us: 1_500_000,
          },
          failure: null,
        },
      ],
    },
  });
  const referenceState: PipelineWorkspaceStage["reference"] =
    state === "draft" || state === "affected" || state === "complete"
      ? {
          state: state === "draft" ? "draft" : "complete",
          draft_revision: 2,
          selected_completion: state === "complete" ? "reference-1" : null,
          source_revision_id: generated.revision_id,
          coverage: {},
          coverage_state: state === "complete" ? "complete" : "incomplete",
          affected_count: state === "affected" ? 2 : 0,
          updated_at: "2026-09-06T00:00:00Z",
        }
      : null;
  return pipelineWorkspace({
    stageOverrides: {
      events: {
        state,
        input_options:
          state === "video-only" || state === "empty" ? [] : [generated],
        selection_revision: state === "video-only" ? null : 1,
        selected_generated_revision_id:
          state === "video-only" || state === "empty"
            ? null
            : generated.revision_id,
        selected_completed_reference_revision_id:
          state === "complete" ? "reference-1" : null,
        runs: state === "video-only" || state === "empty" ? [] : [generatedRun],
        reference: referenceState,
        can_run: state !== "complete",
        can_review: state === "generated-only",
        comparable_run_ids:
          state === "complete" ? ["run-events-1", "run-events-2"] : [],
      },
    },
  });
}

export function roundAnalysisPresentationFixture(): PipelineWorkspace {
  return pipelineWorkspace({
    stageOverrides: {
      round_analyses: {
        state: "complete",
        can_run: false,
        analyses: [
          pipelineAnalysis("analysis-1", {
            state: "complete",
            completed_at: "2026-09-06T00:01:00Z",
            progress: { completed: 1, total: 1 },
          }),
        ],
      },
    },
  });
}
