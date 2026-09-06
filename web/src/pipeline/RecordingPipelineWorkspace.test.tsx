import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import {
  getPrimaryAction,
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
  readPipelineUrlState,
  readRecordingPipelineRoute,
  RecordingPipelineWorkspace,
  recordingPipelineComparePath,
  recordingPipelinePath,
} from "./RecordingPipelineWorkspace";
import { App } from "../App";
import type { PipelineWorkspace, PipelineWorkspaceStage } from "../api/client";

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
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it.each([
    [
      "Continue review",
      {
        has_maintained_reference: true,
        reference: {
          state: "draft",
          draft_revision: 2,
          selected_completion: null,
          source_revision_id: "events-1",
          coverage: null,
          coverage_state: "none",
          affected_count: 0,
          updated_at: null,
        },
        can_run: true,
      },
      "continue_review",
    ],
    ["Run", { can_run: true }, "run"],
    [
      "Review",
      {
        selected_generated_revision_id: "events-1",
        can_run: false,
        can_review: true,
      },
      "review",
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
        has_maintained_reference: false,
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

  it("renders the compact workspace shell and generated/reviewed selectors", async () => {
    const generated = {
      revision_id: "events-2",
      content_type: "events",
      origin: "processor",
      completion_state: "complete",
      coverage_state: "full-recording",
      display_label: "Generated events 2",
      content_sha256: "b".repeat(64),
      input_revision_ids: [],
      producer: {},
      coverage: {},
      created_at: "2026-09-06T00:00:00Z",
    };
    const body = workspace({
      state: "generated-only",
      input_options: [
        generated as PipelineWorkspaceStage["input_options"][number],
      ],
      selection_revision: 4,
      selected_generated_revision_id: generated.revision_id,
      can_run: false,
      can_review: true,
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
      await screen.findByRole("heading", { name: "Recording pipeline" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to recordings" }),
    ).toHaveAttribute("href", "/recordings");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Events task surface" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: "Workspace inspector" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Timeline Rail" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Pipeline stage summary" }),
    ).not.toBeInTheDocument();
    const inspector = screen.getByRole("complementary", {
      name: "Workspace inspector",
    });
    expect(
      [...inspector.querySelectorAll("[data-inspector-section]")].map(
        (section) => section.getAttribute("data-inspector-section"),
      ),
    ).toEqual([
      "progress",
      "action",
      "save-state",
      "selection",
      "metadata",
      "details",
    ]);
    expect(
      within(inspector).getByRole("heading", { name: "Accepted video" }),
    ).toBeInTheDocument();
    expect(
      within(inspector).getByText("Lineage, diagnostics, and history"),
    ).toBeInTheDocument();
    expect(
      within(inspector).getByRole("combobox", {
        name: "Default generated revision",
      }),
    ).toHaveValue(generated.revision_id);
    expect(
      within(inspector).getByRole("button", { name: "Run processor" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Next action")).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Recording pipeline stages" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Events/ }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Generated" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Reviewed" })).toBeEnabled();
    expect(
      screen.getByRole("combobox", { name: "Default generated revision" }),
    ).toHaveValue(generated.revision_id);
    expect(screen.getAllByText("Review").length).toBeGreaterThan(0);
  });

  it("keeps failed blockers and diagnostics visible in the inspector", async () => {
    const blocker = "The accepted recording video is unavailable.";
    const body = workspace(
      {
        state: "failed",
        can_run: false,
        run_blockers: [blocker],
      },
      [
        {
          code: "video_unavailable",
          message: blocker,
          revision_id: null,
        },
      ],
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
        stageKey="events"
        compare={false}
      />,
    );

    const inspector = await screen.findByRole("complementary", {
      name: "Workspace inspector",
    });
    expect(
      within(inspector).getByRole("heading", { name: "Blocked" }),
    ).toBeInTheDocument();
    expect(within(inspector).getAllByText(blocker).length).toBeGreaterThan(0);
    expect(
      within(inspector).getByRole("list", { name: "Pipeline diagnostics" }),
    ).toBeVisible();
    expect(
      within(inspector).getByText("Video Unavailable"),
    ).toBeInTheDocument();
  });

  it("routes shared rail item selection through the restorable URL state", async () => {
    const generated = {
      revision_id: "events-rail-revision",
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
      state: "generated-only",
      input_options: [generated],
      selected_generated_revision_id: generated.revision_id,
      can_run: false,
      can_review: true,
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
          output_revision_ids: [generated.revision_id],
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
                  event_type: "card_played",
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

    const item = await screen.findByRole("button", {
      name: "card_played, 0:02–0:03, succeeded",
    });
    fireEvent.click(item);

    expect(window.location.search).toContain("item=event-rail-1");
    expect(window.location.search).toContain("t_us=2000000");
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
              state: "generated-only",
              input_options: [generated],
              selected_generated_revision_id: revisionId,
              can_run: false,
              can_review: true,
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
                  },
                ],
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

    expect(
      await screen.findByRole("heading", { name: "Visible-card suggestions" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: "1 visible-card proposal" }),
    ).toBeInTheDocument();
    const railItems = await screen.findAllByRole("button", {
      name: /Frame 1 · 4\.000 s/,
    });
    fireEvent.click(railItems[0]);
    expect(window.location.search).toContain(`item=${itemId}`);
    expect(window.location.search).toContain("t_us=4000000");
  });

  it("hydrates reviewed event selection into the shared rail", async () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/events?view=reviewed",
    );
    const generated = {
      revision_id: "events-reviewed-source",
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
      state: "draft",
      input_options: [generated],
      selected_generated_revision_id: generated.revision_id,
      reference: {
        state: "draft",
        draft_revision: 1,
        selected_completion: null,
        source_revision_id: generated.revision_id,
        coverage: null,
        coverage_state: "none",
        affected_count: 0,
        updated_at: null,
      },
      can_run: false,
      can_review: false,
    });
    const reference = {
      recording_id: RECORDING_ID,
      content_type: "events",
      state: {
        recording_id: RECORDING_ID,
        content_type: "events",
        draft_revision: 1,
        draft_state: "draft",
        source_revision_id: generated.revision_id,
        selected_completed_revision_id: null,
        updated_at: "2026-09-06T00:00:00Z",
      },
      draft: {
        recording_id: RECORDING_ID,
        content_type: "events",
        revision: 1,
        source_revision_id: generated.revision_id,
        items: [
          {
            item_id: "reviewed-event-1",
            base_item_id: "generated-event-1",
            review_state: "pending",
            item: {
              event_id: "generated-event-1",
              event_type: "card_played",
              start_us: 1_000_000,
              end_us: 1_500_000,
            },
          },
        ],
        coverage: null,
        impact: [],
        updated_at: "2026-09-06T00:00:00Z",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input).endsWith("/pipeline/references/events")
                ? reference
                : body,
            ),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
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

    await screen.findByRole("heading", { name: "CardEvent review" });
    const item = await screen.findByRole("button", {
      name: "Card Played, 0:01–0:02, pending",
    });
    fireEvent.click(item);

    expect(window.location.search).toContain("item=reviewed-event-1");
    expect(window.location.search).toContain("t_us=1000000");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
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
      view: "reviewed",
      revision: "revision-2",
      item: null,
      tUs: 17,
      left: null,
      right: null,
      reference: null,
      analysis: null,
    });
    expect(
      recordingPipelinePath(RECORDING_ID, "events", { view: "reviewed" }),
    ).toBe("/recordings/recording-shell/pipeline/events?view=reviewed");
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
      await screen.findByLabelText(
        `Table-observation source video ${RECORDING_ID}`,
      ),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /^observation-1,.*0:12/i }),
    );
    expect(window.location.search).toContain("item=observation-1");
    expect(window.location.search).toContain("t_us=12000000");
    expect(screen.getByText("Observation observation-1")).toBeInTheDocument();
    expect(screen.getByText("1 visible card")).toBeInTheDocument();
  });

  it("uses the shared source surface, inspector, and rail for comparisons", async () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-shell/pipeline/events/compare?left=run-left&right=run-right&reference=reference-compare-1",
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
        revision_id: "reference-compare-1",
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
          event_type: "card_played",
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
      vi.fn<typeof fetch>((_input, init) =>
        Promise.resolve(
          new Response(
            JSON.stringify(init?.method === "POST" ? comparison : body),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
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
      await screen.findByLabelText(`Comparison source video ${RECORDING_ID}`),
    ).toBeInTheDocument();
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
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
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
        ),
      ),
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="round_analyses"
        compare={false}
      />,
    );

    expect(
      await screen.findByLabelText(
        `Round-analysis source video ${RECORDING_ID}`,
      ),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /round-rail-1, 0:18.*complete/i }),
    );
    expect(window.location.search).toContain(`analysis=${analysisId}`);
    expect(window.location.search).toContain("t_us=18000000");
    expect(screen.getByText("Selected round analysis")).toBeInTheDocument();
    expect(screen.getByText("observations-rail-1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open evidence and counterfactual workbench",
      }),
    ).toBeInTheDocument();
  });

  it("reloads the winning selection after an optimistic conflict", async () => {
    const first = workspace({
      state: "generated-only",
      input_options: [
        {
          revision_id: "events-1",
          content_type: "events",
          origin: "processor",
          completion_state: "complete",
          coverage_state: "full-recording",
          display_label: "Generated events 1",
          content_sha256: "b".repeat(64),
          input_revision_ids: [],
          producer: {},
          coverage: {},
          created_at: "2026-09-06T00:00:00Z",
        },
        {
          revision_id: "events-2",
          content_type: "events",
          origin: "processor",
          completion_state: "complete",
          coverage_state: "full-recording",
          display_label: "Generated events 2",
          content_sha256: "c".repeat(64),
          input_revision_ids: [],
          producer: {},
          coverage: {},
          created_at: "2026-09-06T00:00:01Z",
        },
      ],
      selection_revision: 4,
      selected_generated_revision_id: "events-1",
      can_run: false,
      can_review: true,
    });
    const winner = workspace({
      ...first.stages[0],
      selection_revision: 5,
      selected_generated_revision_id: "events-2",
    });
    let workspaceCalls = 0;
    const fetchMock = vi.fn<typeof fetch>((_input, init): Promise<Response> => {
      if (init?.method === "PUT") {
        return Promise.resolve(new Response("{}", { status: 409 }));
      }
      workspaceCalls += 1;
      const response = workspaceCalls > 1 ? winner : first;
      return Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="events"
        compare={false}
      />,
    );
    const selector = await screen.findByRole("combobox", {
      name: "Default generated revision",
    });
    await userEvent.setup().selectOptions(selector, "events-2");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The generated selection changed elsewhere. The winning selection is shown.",
    );
    await waitFor(() => expect(selector).toHaveValue("events-2"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/recordings/recording-shell/pipeline/events/selection",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          expected_revision: 4,
          selected_generated_revision_id: "events-2",
        }),
      }),
    );
    expect(
      within(screen.getByRole("main")).getAllByText("Review").length,
    ).toBeGreaterThan(0);
  });
});
