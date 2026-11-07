import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import {
  getPrimaryAction,
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
} from "./RecordingPipelineWorkspace";
import { RecordingPipelineWorkspace } from "./RecordingPipelineWorkspace";
import type {
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";
vi.mock("./AutomatedPipelineControls", () => ({
  AutomatedPipelineControls: () => null,
}));

const RECORDING_ID = "recording-shell";

function stage(
  key: PipelineWorkspaceStage["key"] = "events",
  overrides: Record<string, unknown> = {},
): PipelineWorkspaceStage {
  return {
    key,
    processor_key: `${key}-processor`,
    processor_type: `${key}-processor`,
    output_content_type: key,
    state: "video-only",
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

function workspace(
  overrides: Record<string, unknown> = {},
  diagnostics: PipelineWorkspace["diagnostics"] = [],
): PipelineWorkspace {
  return {
    schema_version: "pipeline-workspace/v1",
    recording_id: RECORDING_ID,
    video: {
      schema_version: "recording-video/v1",
      recording_id: RECORDING_ID,
      relative_path: "recordings/recording-shell/video.mp4",
      video_sha256: "a".repeat(64),
      byte_length: 10,
      duration_us: 90_000_000,
    },
    stages: PIPELINE_STAGE_KEYS.map((key) =>
      stage(key, key === "events" ? overrides : {}),
    ),
    diagnostics,
  };
}

describe("recording pipeline workspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it.each([
    ["Run", { can_run: true }, "run"],
    [
      "Blocked",
      {
        selected_generated_revision_id: "events-1",
        can_run: false,
      },
      "blocked",
    ],
    [
      "Compare",
      {
        selected_completed_reference_revision_id: "reference-1",
        comparable_run_ids: ["run-1", "run-2"],
        can_run: false,
      },
      "compare",
    ],
    [
      "Open analysis",
      {
        key: "round_analyses",
        can_run: false,
        analyses: [{ state: "complete" }],
      },
      "open_analysis",
    ],
    ["Run again", { selected_generated_revision_id: "events-1" }, "run_again"],
    [
      "Blocked",
      { can_run: false, run_blockers: ["Select an input first."] },
      "blocked",
    ],
  ])("applies the primary action priority: %s", (label, overrides, kind) => {
    const action = primaryActionForStage(stage("events", overrides));
    expect(action).toMatchObject({ label, kind });
    expect(getPrimaryAction(stage("events", overrides))).toEqual(action);
  });

  it("routes shared rail item selection through the restorable URL state", async () => {
    const generated = {
      revision_id: "events-rail-revision",
      node_id: "node-events-rail-revision",
      node_revision_id: "node-revision-events-rail-revision",
      is_current_head: true,
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
    } as PipelineWorkspaceStage["input_options"][number];
    const body = workspace({
      state: "data-available",
      input_options: [generated],
      selected_generated_revision_id: generated.node_revision_id,
      can_run: false,
      runs: [
        {
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
          output_revision_ids: [generated.node_revision_id],
          progress: { completed: 1, total: 1 },
          request: {},
          run_id: "run-rail-1",
          started_at: null,
          state: {
            items: [
              {
                item_id: "event-rail-1",
                status: "succeeded",
                result: {
                  event_type: "card_state_changed",
                  start_us: 2_000_000,
                  end_us: 3_000_000,
                },
                failure: null,
              },
            ],
          },
          status: "complete",
          updated_at: "2026-09-06T00:00:00Z",
        },
      ],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="events"
        compare={false}
      />,
    );

    expect(
      await screen.findByRole("complementary", {
        name: "Workspace inspector",
      }),
    ).toHaveTextContent("No data set selected");
    expect(
      screen.queryByRole("button", {
        name: "Card-state change, 0:02–0:03, succeeded",
      }),
    ).toBeNull();
  });

  it("uses the shared rail and exact-frame surface for generated visible cards", async () => {
    const revisionId = "visible-rail-revision";
    const runId = "visible-rail-run";
    const itemId = "visible-frame-1";
    const frameIdentity = {
      requested_time_us: 4_000_000,
      frame_index: 120,
      presentation_timestamp_us: 4_000_000,
      width: 640,
      height: 360,
      image_sha256: "c".repeat(64),
    };
    const generated = {
      revision_id: revisionId,
      node_id: `node-${revisionId}`,
      node_revision_id: `node-revision-${revisionId}`,
      is_current_head: true,
      content_type: "visible_cards",
      origin: "processor",
      completion_state: "complete",
      coverage_state: "full-recording",
      display_label: "Generated visible cards",
      content_sha256: "d".repeat(64),
      input_revision_ids: [],
      producer: {},
      coverage: {},
      created_at: "2026-09-06T00:00:00Z",
    } as PipelineWorkspaceStage["input_options"][number];
    const body = workspace();
    body.stages = PIPELINE_STAGE_KEYS.map((key) =>
      stage(
        key,
        key === "visible_cards"
          ? {
              state: "data-available",
              input_options: [generated],
              selected_generated_revision_id: revisionId,
              can_run: false,
              runs: [
                {
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
                  output_revision_ids: [revisionId],
                  progress: { completed: 1, total: 1 },
                  request: {},
                  run_id: runId,
                  started_at: null,
                  state: {
                    items: [
                      {
                        item_id: itemId,
                        status: "succeeded",
                        result: {},
                        failure: null,
                      },
                    ],
                  },
                  status: "complete",
                  updated_at: "2026-09-06T00:00:00Z",
                },
              ],
            }
          : {},
      ),
    );
    const result = {
      run_id: runId,
      recording_id: RECORDING_ID,
      processor_type: "visible-card-detection",
      status: "complete",
      attempt: 1,
      request: {},
      state: {},
      revisions: [
        {
          manifest: { revision_id: revisionId },
          content: {
            outcomes: [
              {
                event_id: itemId,
                frame_identity: frameIdentity,
                status: "detected",
                candidates: [
                  {
                    card_id: "proposal-1",
                    geometry: {
                      kind: "detector-box/v1",
                      box_2d: {
                        x_min: 100,
                        y_min: 100,
                        x_max: 400,
                        y_max: 300,
                      },
                    },
                    normalization: { width: 640, height: 360 },
                    side: "unknown",
                  },
                ],
                ignored_regions: [],
                error: null,
              },
            ],
          },
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input).includes("/pipeline/visible-cards/")
                ? result
                : body,
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="visible_cards"
        compare={false}
      />,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      await screen.findByText(
        "Select a Visible cards data set in the lineage drawer.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "1 visible-card proposal" }),
    ).toBeNull();
  });

  it("does not open the legacy visible-card review editor without a selected node", async () => {
    const revisionId = "visible-review-revision";
    const defaultRevisionId = "visible-review-default";
    const runId = "visible-review-run";
    const defaultRunId = "visible-review-default-run";
    const itemId = "visible-review-frame-1";
    const generated = {
      revision_id: revisionId,
      node_id: `node-${revisionId}`,
      node_revision_id: `node-revision-${revisionId}`,
      is_current_head: true,
      content_type: "visible_cards",
      origin: "processor",
      completion_state: "complete",
      coverage_state: "full-recording",
      display_label: "Generated visible cards",
      content_sha256: "d".repeat(64),
      input_revision_ids: [],
      producer: {},
      coverage: {},
      created_at: "2026-09-06T00:00:00Z",
    } as PipelineWorkspaceStage["input_options"][number];
    const defaultGenerated = {
      ...generated,
      revision_id: defaultRevisionId,
      display_label: "Default generated visible cards",
    } as PipelineWorkspaceStage["input_options"][number];
    const frameIdentity = {
      requested_time_us: 4_000_000,
      frame_index: 120,
      presentation_timestamp_us: 4_000_000,
      width: 640,
      height: 360,
      image_sha256: "c".repeat(64),
    };
    const body = workspace();
    body.stages = PIPELINE_STAGE_KEYS.map((key) =>
      stage(
        key,
        key === "visible_cards"
          ? {
              state: "data-available",
              input_options: [generated, defaultGenerated],
              selected_generated_revision_id: defaultRevisionId,
              can_run: false,
              runs: [
                {
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
                  output_revision_ids: [revisionId],
                  progress: { completed: 1, total: 1 },
                  request: {},
                  run_id: runId,
                  started_at: null,
                  state: {
                    items: [
                      {
                        item_id: itemId,
                        status: "succeeded",
                        result: {},
                        failure: null,
                      },
                    ],
                  },
                  status: "complete",
                  updated_at: "2026-09-06T00:00:00Z",
                },
                {
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
                  output_revision_ids: [defaultRevisionId],
                  progress: { completed: 1, total: 1 },
                  request: {},
                  run_id: defaultRunId,
                  started_at: null,
                  state: {
                    items: [
                      {
                        item_id: itemId,
                        status: "succeeded",
                        result: {},
                        failure: null,
                      },
                    ],
                  },
                  status: "complete",
                  updated_at: "2026-09-06T00:00:00Z",
                },
              ],
            }
          : {},
      ),
    );
    const result = {
      run_id: runId,
      recording_id: RECORDING_ID,
      processor_type: "visible-card-detection",
      status: "complete",
      attempt: 1,
      request: {},
      state: {},
      revisions: [
        {
          manifest: { revision_id: revisionId },
          content: {
            outcomes: [
              {
                event_id: itemId,
                frame_identity: frameIdentity,
                status: "detected",
                candidates: [
                  {
                    card_id: "proposal-1",
                    geometry: {
                      kind: "detector-box/v1",
                      box_2d: {
                        x_min: 100,
                        y_min: 100,
                        x_max: 400,
                        y_max: 300,
                      },
                    },
                    normalization: { width: 640, height: 360 },
                    side: "face_down",
                  },
                ],
                ignored_regions: [],
                error: null,
              },
            ],
          },
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        const path = String(input);
        if (path.endsWith("/pipeline/references/visible_cards")) {
          return Promise.resolve(
            new Response(JSON.stringify({ message: "not found" }), {
              status: 404,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        if (
          path.includes("/pipeline/visible-cards/") &&
          path.includes(`${defaultRunId}/result`)
        ) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ message: "default result omitted" }),
              {
                status: 404,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify(
              path.includes("/pipeline/visible-cards/") ? result : body,
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }),
    );

    window.history.pushState(
      {},
      "",
      `/recordings/${RECORDING_ID}/pipeline/visible_cards?view=generated&revision=${revisionId}`,
    );
    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="visible_cards"
        compare={false}
      />,
    );

    expect(
      await screen.findByText(
        "Select a Visible cards data set in the lineage drawer.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Start visible-card review" }),
    ).toBeNull();
  });
});
