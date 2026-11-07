import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";

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
import type { PipelineWorkspace, PipelineWorkspaceStage } from "../api/client";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";

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

  it("renders the compact workspace shell and two-row navigation", async () => {
    const generated = {
      revision_id: "events-2",
      node_id: "node-events-2",
      node_revision_id: "node-revision-events-2",
      is_current_head: true,
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
      state: "data-available",
      input_options: [
        generated as PipelineWorkspaceStage["input_options"][number],
      ],
      selection_revision: 4,
      selected_generated_revision_id: generated.node_revision_id,
      can_run: false,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        if (String(input).endsWith("/pipeline/lineage")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                schema_version: "pipeline-lineage-graph/v1",
                nodes: [
                  {
                    node_id: "events-lineage-node",
                    name: "First pass",
                    content_type: "events",
                    source: { recording_id: RECORDING_ID },
                    head_revision_id: "events-lineage-r1",
                  },
                ],
                revisions: [
                  {
                    node_id: "events-lineage-node",
                    revision_id: "events-lineage-r1",
                    content_sha256: "d".repeat(64),
                    created_at: "2026-09-06T00:00:00Z",
                  },
                ],
                runs: [],
                artifacts: [],
                edges: [],
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        return Promise.resolve(
          String(input).endsWith("/video")
            ? new Response(new Blob(["video"]), { status: 200 })
            : new Response(JSON.stringify(body), {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
        );
      }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:workspace-test");

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
      "automated-pipeline",
      "action",
      "events",
      "save-state",
      "selection",
      "metadata",
      "details",
    ]);
    expect(
      within(inspector).getByRole("heading", { name: "Accepted video" }),
    ).toBeInTheDocument();
    expect(
      screen
        .getByRole("region", { name: "Timeline Rail" })
        .querySelector("video"),
    ).toBeNull();
    expect(
      within(screen.getByRole("region", { name: "Timeline Rail" })).queryByRole(
        "button",
        { name: "Play recording" },
      ),
    ).not.toBeInTheDocument();
    expect(
      within(inspector).getByText("Lineage, diagnostics, and history"),
    ).toBeInTheDocument();
    expect(
      within(inspector).queryByText("Reference source"),
    ).not.toBeInTheDocument();
    expect(
      within(inspector).queryByText("Reference revision"),
    ).not.toBeInTheDocument();
    expect(
      within(inspector).getByRole("combobox", {
        name: "Default generated revision",
      }),
    ).toHaveValue(generated.node_revision_id);
    expect(
      within(inspector).getByRole("button", { name: "Run processor" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Next action")).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Recording pipeline steps" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Visible cards",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Events/ }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: "Virtual scenes" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Generated" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reviewed" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("No data set selected")).toHaveLength(7);
    expect(
      screen.getByRole("combobox", { name: "Default generated revision" }),
    ).toHaveValue(generated.node_revision_id);
    expect(screen.queryByRole("button", { name: "Review" })).toBeNull();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Show lineage" }));
    const lineage = await screen.findByRole("region", {
      name: "Pipeline lineage",
    });
    await userEvent
      .setup()
      .click(
        within(lineage).getByRole("button", { name: "r events-lineage-r1" }),
      );
    const savedSelection = JSON.parse(
      readPipelineUrlState(window.location.search).lineage ?? "null",
    );
    expect(savedSelection.selected.events).toEqual({
      node_id: "events-lineage-node",
      revision_id: "events-lineage-r1",
    });
  });

  it("opens Virtual scenes as an inspector-backed separate step", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(workspace()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="virtual_scenes"
        compare={false}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Virtual scenes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No virtual scene is selected for this lineage."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Virtual scenes" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Run processor" })).toBeNull();
    expect(
      screen.getByRole("complementary", { name: "Workspace inspector" }),
    ).toBeInTheDocument();
  });

  it("keeps a stale explicit lineage link and does not select a substitute", async () => {
    const selection = JSON.stringify({
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        events: { node_id: "deleted-node", revision_id: "deleted-revision" },
      },
    });
    const body = workspace();
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path.endsWith("/video")) {
        return Promise.resolve(
          new Response(new Blob(["video"]), { status: 200 }),
        );
      }
      if (!path.includes("/pipeline")) {
        return Promise.resolve(new Response("Not found", { status: 404 }));
      }
      const value = path.endsWith("/pipeline/lineage")
        ? {
            schema_version: "pipeline-lineage-graph/v1",
            nodes: [],
            revisions: [],
            runs: [],
            artifacts: [],
            edges: [],
          }
        : body;
      return Promise.resolve(
        new Response(JSON.stringify(value), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:lineage-test");
    window.history.pushState(
      {},
      "",
      `/recordings/${RECORDING_ID}/pipeline/events?lineage=${encodeURIComponent(selection)}`,
    );

    render(
      <RecordingPipelineWorkspace
        recordingId={RECORDING_ID}
        stageKey="events"
        compare={false}
      />,
    );

    const unavailableNotice =
      "The saved lineage selection is unavailable. No other revision was selected.";
    const invalidNotice =
      "The saved lineage selection is invalid. No other revision was selected.";
    expect(await screen.findByText(unavailableNotice)).toBeInTheDocument();
    expect(readPipelineUrlState(window.location.search).lineage).toBe(
      selection,
    );
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "PUT"),
    ).toBe(false);

    window.history.pushState(
      {},
      "",
      `/recordings/${RECORDING_ID}/pipeline/events?lineage=not-json`,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByText(invalidNotice)).toBeInTheDocument();

    window.history.back();
    expect(await screen.findByText(unavailableNotice)).toBeInTheDocument();
    window.history.forward();
    expect(await screen.findByText(invalidNotice)).toBeInTheDocument();
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
      state: "data-available",
      input_options: [
        {
          revision_id: "events-1",
          node_id: "events-node-1",
          node_revision_id: "events-node-r1",
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
          node_id: "events-node-2",
          node_revision_id: "events-node-r2",
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
      if (String(_input).endsWith("/pipeline/lineage")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              schema_version: "pipeline-lineage-graph/v1",
              nodes: [],
              revisions: [],
              runs: [],
              artifacts: [],
              edges: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
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
    await userEvent.setup().selectOptions(selector, "events-node-r2");

    expect(
      await screen.findByText(
        "The processor input changed elsewhere. The winning selection is shown.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(selector).toHaveValue("events-node-r2"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/recordings/recording-shell/pipeline/events/selection",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          expected_revision: 4,
          selected_generated: {
            node_id: "events-node-2",
            revision_id: "events-node-r2",
          },
        }),
      }),
    );
    expect(
      screen.queryByRole("button", { name: "Review" }),
    ).not.toBeInTheDocument();
  });
});
