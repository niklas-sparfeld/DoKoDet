import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import {
  getPrimaryAction,
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
} from "./RecordingPipelineWorkspace";
import {
  readPipelineUrlState,
  readRecordingPipelineRoute,
  recordingPipelineComparePath,
  recordingPipelinePath,
} from "./recordingPipelineUrl";
import { RecordingPipelineWorkspace } from "./RecordingPipelineWorkspace";
import { App } from "../App";
import type {
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";
import { resolvedStatus, resolvedTimeline } from "../test/roundAnalysisFixture";
import { JobStateProvider } from "../jobs/JobState";
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

  it("does not hydrate a reviewed event selection from the legacy view URL", async () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/events?view=reviewed",
    );
    const generated = {
      revision_id: "events-reviewed-source",
      node_id: "node-events-reviewed-source",
      node_revision_id: "node-revision-events-reviewed-source",
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
      screen.queryByRole("complementary", {
        name: "CardEvent review controls",
      }),
    ).toBeNull();
  });

  it("is composed by App for a recording-owned pipeline path", async () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/events?view=generated",
    );
    const body = workspace();
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

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recording pipeline" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe(
      "/recordings/recording-shell/pipeline/events",
    );
  });

  it("redirects the detail path without a network redirect and preserves URL state helpers", async () => {
    const body = workspace();
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell?view=generated&revision=old&item=event-1&t_us=100",
    );
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
        stageKey={null}
        compare={false}
      />,
    );

    await waitFor(() =>
      expect(window.location.pathname).toBe(
        "/recordings/recording-shell/pipeline/events",
      ),
    );
    expect(readRecordingPipelineRoute(window.location.pathname)).toMatchObject({
      recordingId: RECORDING_ID,
      stage: "events",
      compare: false,
    });
    expect(
      readPipelineUrlState("?view=reviewed&revision=revision-2&t_us=17"),
    ).toEqual({
      lineage: null,
      item: null,
      tUs: 17,
      left: null,
      right: null,
      reference: null,
      analysis: null,
      row: null,
      hypothesis: null,
      frameReviewQueue: null,
    });
    expect(
      recordingPipelinePath(RECORDING_ID, "events", { lineage: "choice-1" }),
    ).toBe("/recordings/recording-shell/pipeline/events?lineage=choice-1");
    expect(
      recordingPipelineComparePath(RECORDING_ID, "events", {
        left: "run/1",
        right: "run/2",
        reference: "reference/1",
      }),
    ).toBe(
      "/recordings/recording-shell/pipeline/events/compare?left=run%2F1&right=run%2F2&reference=reference%2F1",
    );
  });

  it("removes stale stage identifiers and clamps playback position", async () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/table_observations?view=invalid&revision=missing&item=old&t_us=999999999",
    );
    const body = workspace();
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
        stageKey="table_observations"
        compare={false}
      />,
    );

    expect(
      await screen.findByText(
        "Some saved pipeline URL state was no longer available and was reset.",
      ),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?t_us=90000000");
  });

  it("uses an observation interval to synchronize the source surface and URL", async () => {
    const observationRun = {
      run_id: "observation-run-1",
      status: "complete",
      attempt: 1,
      input_revision_ids: ["events-1", "visible-1", "identity-1"],
      implementation: { name: "observation-assembler", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
      progress: { completed: 1, total: 1 },
      failure: null,
      output_revision_ids: ["observations-1"],
      state: {
        status: "complete",
        progress: { completed: 1, total: 1 },
        items: [
          {
            item_id: "observation-1",
            status: "succeeded",
            result: {
              observation_id: "observation-1",
              observed_at_ms: 12_000,
              status: "observed",
              capabilities: ["identity_candidates"],
              cards: [
                {
                  observed_card_id: "card-1",
                  identity_status: "classified",
                  identity_candidates: [],
                },
              ],
            },
          },
        ],
      },
    } as unknown as PipelineWorkspaceStage["runs"][number];
    const body = workspace();
    body.stages[3] = stage("table_observations", {
      state: "complete",
      selected_generated_revision_id: "observations-1",
      input_options: [
        {
          revision_id: "observations-1",
          content_type: "table_observations",
          origin: "processor",
          completion_state: "complete",
          coverage_state: "assembled-events",
          display_label: "Generated observations",
          content_sha256: "b".repeat(64),
          input_revision_ids: ["events-1", "visible-1", "identity-1"],
          producer: {},
          coverage: {},
          created_at: "2026-09-06T00:00:00Z",
        },
      ],
      runs: [observationRun],
      can_run: true,
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
        stageKey="table_observations"
        compare={false}
      />,
    );

    expect(
      await screen.findByLabelText("Table observation source frame"),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(`Table-observation source video ${RECORDING_ID}`),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /^observation-1,.*0:12/i }),
    );
    expect(window.location.search).toContain("item=observation-1");
    expect(window.location.search).toContain("t_us=12000000");
    const observationInspector = screen.getByLabelText(
      "Selected table observation",
    );
    expect(
      within(observationInspector).getByText("observed"),
    ).toBeInTheDocument();
    expect(
      within(observationInspector).getByText(
        "No exact visible-card source revision is linked. Geometry is unavailable.",
      ),
    ).toBeInTheDocument();
  });

  it("uses the shared source surface, inspector, and rail for comparisons", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:comparison-frame");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/events/compare?left=run-left&right=run-right&reference=node-revision-reference-compare-1",
    );
    const body = workspace();
    body.stages[0] = stage("events", {
      state: "complete",
      can_run: false,
      comparable_run_ids: ["run-left", "run-right"],
      selected_completed_reference_revision_id: "reference-compare-1",
      input_options: [
        {
          revision_id: "reference-compare-1",
          node_id: "node-reference-compare-1",
          node_revision_id: "node-revision-reference-compare-1",
          content_type: "events",
          origin: "manual",
          completion_state: "complete",
          coverage_state: "full-recording",
          display_label: "Reviewed events",
          content_sha256: "b".repeat(64),
          input_revision_ids: [],
          producer: {},
          coverage: {},
          created_at: "2026-09-06T00:00:00Z",
        },
      ],
      runs: ["run-left", "run-right"].map((run_id) => ({
        run_id,
        status: "complete",
        created_at: "2026-09-06T00:00:00Z",
        input_revision_ids: ["events-input-1"],
        output_revision_ids: [`${run_id}-output`],
        implementation: { name: "event-detector", version: "v1" },
        progress: { completed: 1, total: 1 },
        failure: null,
        state: {},
      })),
    });
    const comparison = {
      schema_version: "pipeline-comparison/v1",
      comparison_id: "comparison-rail-1",
      recording_id: RECORDING_ID,
      content_type: "events",
      mode: "paired_processor",
      algorithm_version: "pipeline-comparison.v2",
      left: {
        run_id: "run-left",
        revision_id: "run-left-output",
        status: "complete",
        input_revision_ids: ["events-input-1"],
        content_sha256: "c".repeat(64),
        implementation: { name: "event-detector", version: "v1" },
        model: null,
        configuration: {},
        extraction_policy: {},
        failure: null,
      },
      right: {
        run_id: "run-right",
        revision_id: "run-right-output",
        status: "complete",
        input_revision_ids: ["events-input-1"],
        content_sha256: "d".repeat(64),
        implementation: { name: "event-detector", version: "v1" },
        model: null,
        configuration: {},
        extraction_policy: {},
        failure: null,
      },
      reference: {
        revision_id: "node-revision-reference-compare-1",
        input_revision_ids: [],
        content_sha256: "b".repeat(64),
        origin: "manual",
      },
      scope: {
        reviewed: [{ start_us: 0, end_us: 90_000_000 }],
        common_covered: [{ start_us: 0, end_us: 90_000_000 }],
        left_only: [],
        right_only: [],
        reviewed_frame_identities: [],
        common_frame_identities: [],
        left_only_frame_identities: [],
        right_only_frame_identities: [],
      },
      matching_policy: {
        policy_id: "event-timing/v1",
        kind: "event_timing",
        anchor: "start_us",
        tolerance_us: 50_000,
      },
      counts: {
        left: {
          reference_events: 1,
          run_events: 1,
          matches: 0,
          misses: 1,
          extras: 0,
          failures: 0,
          not_reviewed: 0,
          unpaired_input: 0,
        },
        right: {
          reference_events: 1,
          run_events: 1,
          matches: 0,
          misses: 1,
          extras: 0,
          failures: 0,
          not_reviewed: 0,
          unpaired_input: 0,
        },
      },
      metrics: { left: {}, right: {} },
      paired_delta: null,
      items: [
        {
          item_id: "comparison-outcome-1",
          side: "left",
          outcome: "miss",
          source_time_us: 12_000_000,
          event_type: "card_state_changed",
          reference_event_id: null,
          run_event_id: null,
          reference_event: null,
          run_event: null,
          delta_us: null,
          source_links: { derived_view: null },
          frame_identity: null,
          reference_card_id: null,
          run_card_id: null,
          reference_card: null,
          run_card: null,
          iou: null,
          reference_identity: null,
          run_identity: null,
          reference_candidates: null,
          run_candidates: null,
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input, init) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof Request
              ? input.url
              : input.href;
        if (url.includes("/exact-event/")) {
          const requestedTimeUs = Number(url.split("/").at(-1));
          return Promise.resolve(
            new Response("frame", {
              status: 200,
              headers: {
                ETag: `"${"c".repeat(64)}"`,
                "X-DokoDetector-Source-Sha256": "a".repeat(64),
                "X-DokoDetector-Frame-Index": "4",
                "X-DokoDetector-Frame-Width": "640",
                "X-DokoDetector-Frame-Height": "360",
                "X-DokoDetector-Requested-Time-Us": String(requestedTimeUs),
                "X-DokoDetector-Frame-Time-Us": String(requestedTimeUs),
              },
            }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify(init?.method === "POST" ? comparison : body),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }),
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="events"
        compare
      />,
    );

    const inspector = await screen.findByRole("complementary", {
      name: "Workspace inspector",
    });
    expect(
      within(inspector).getByRole("combobox", { name: "Left terminal run" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Source-ordered outcomes"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      await screen.findByRole("button", { name: /miss.*0:12.*miss/i }),
    );
    expect(window.location.search).toContain("item=comparison-outcome-1");
    expect(window.location.search).toContain("t_us=12000000");
    expect(
      await screen.findAllByLabelText("Spatial evidence surface"),
    ).toHaveLength(2);
    expect(
      screen.queryByLabelText(`Comparison source video ${RECORDING_ID}`),
    ).not.toBeInTheDocument();
    expect(
      within(inspector).getByText(/Matching policy: event-timing/),
    ).toBeInTheDocument();
  });

  it("uses the shared source surface and rail for round analyses", async () => {
    const analysisId = "analysis-rail-1";
    const body = workspace();
    body.stages[4] = stage("round_analyses", {
      state: "complete",
      can_run: true,
      analyses: [
        {
          analysis_id: analysisId,
          recording_id: RECORDING_ID,
          round_id: "round-rail-1",
          session_id: "session-rail-1",
          state: "complete",
          progress: { completed: 2, total: 2 },
          input_revision_ids: ["observations-rail-1"],
          request: {
            rules_version: "v1",
            requested_time_us: 18_000_000,
          },
          created_at: "2026-09-06T00:00:00Z",
          started_at: null,
          completed_at: "2026-09-06T00:00:01Z",
          failure: null,
        },
      ],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        const url = String(input);
        if (url.includes("/v1/round-analyses/") && url.endsWith("/timeline")) {
          return Promise.resolve(
            new Response(JSON.stringify(resolvedTimeline), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        if (url.includes("/v1/round-analyses/")) {
          return Promise.resolve(
            new Response(JSON.stringify(resolvedStatus), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify(
              String(input).endsWith(`/recordings/${RECORDING_ID}`)
                ? {
                    recording_id: RECORDING_ID,
                    session_id: "session-rail-1",
                    round_id: "round-rail-1",
                    source: {
                      game_id: "game-rail-1",
                      round_id: "round-rail-1",
                    },
                  }
                : body,
            ),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }),
    );

    render(
      <JobStateProvider>
        <RecordingPipelineWorkspace
          recordingId={RECORDING_ID}
          stageKey="round_analyses"
          compare={false}
        />
      </JobStateProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", {
        name: /round-rail-1, 0:18.*complete/i,
      }),
    );
    expect(document.querySelector("[data-analysis-frame]")).toBeInTheDocument();
    expect(window.location.search).toContain(`analysis=${analysisId}`);
    expect(window.location.search).toContain("t_us=18000000");
    expect(screen.getByText("Selected analysis")).toBeInTheDocument();
    expect(
      document.querySelector('[data-analysis-inspector-slot="details"]'),
    ).toBeInTheDocument();
    expect(
      document.querySelector('[data-slot="center"] video'),
    ).not.toBeInTheDocument();
  });
});
