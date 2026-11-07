import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import {
  getPrimaryAction,
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
} from "./RecordingPipelineWorkspace";
import { readPipelineUrlState } from "./recordingPipelineUrl";
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

  it("shows loading instead of the prior recording while the new one loads", async () => {
    const firstWorkspace = {
      ...workspace(),
      recording_id: "first-recording",
      video: { ...workspace().video, recording_id: "first-recording" },
    };
    let resolveSecond!: (response: Response) => void;
    const secondResponse = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.endsWith("/pipeline/lineage")) {
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
      if (url === "/api/recordings/first-recording/pipeline?stage=events") {
        return Promise.resolve(
          new Response(JSON.stringify(firstWorkspace), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/api/recordings/second-recording/pipeline?stage=events") {
        return secondResponse;
      }
      if (url.endsWith("/video"))
        return Promise.resolve(
          new Response(new Blob(["video"]), { status: 200 }),
        );
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:workspace-switch");

    const view = render(
      <RecordingPipelineWorkspace
        recordingId="first-recording"
        stageKey="events"
        compare={false}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Recording pipeline" }),
    ).toBeInTheDocument();

    view.rerender(
      <RecordingPipelineWorkspace
        recordingId="second-recording"
        stageKey="events"
        compare={false}
      />,
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Loading recording pipeline…",
    );
    expect(
      screen.queryByRole("heading", { name: "Recording pipeline" }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/recordings/second-recording/pipeline?stage=events",
        expect.anything(),
      ),
    );

    resolveSecond(
      new Response(
        JSON.stringify({
          ...firstWorkspace,
          recording_id: "second-recording",
          video: { ...firstWorkspace.video, recording_id: "second-recording" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    expect(
      await screen.findByRole("heading", { name: "Recording pipeline" }),
    ).toBeInTheDocument();
  });

  it("chooses the root route stage from the current recording workspace", async () => {
    const workspaceFor = (recordingId: string, hasObservations: boolean) => {
      const base = workspace();
      return {
        ...base,
        recording_id: recordingId,
        video: { ...base.video, recording_id: recordingId },
        stages: base.stages.map((currentStage) =>
          currentStage.key === "table_observations" && hasObservations
            ? {
                ...currentStage,
                state: "data-available" as const,
                input_options: [
                  {
                    origin: "processor",
                    node_revision_id: "observations-r1",
                  },
                ],
              }
            : currentStage,
        ),
      };
    };
    let resolveSecond!: (response: Response) => void;
    const secondWorkspace = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.endsWith("/pipeline/lineage")) {
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
      if (url === "/api/recordings/first-recording/pipeline?stage=events") {
        return Promise.resolve(
          new Response(JSON.stringify(workspaceFor("first-recording", false)), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/api/recordings/second-recording/pipeline?stage=events")
        return secondWorkspace;
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(URL, "createObjectURL").mockReturnValue(
      "blob:workspace-root-switch",
    );
    window.history.pushState({}, "", "/recordings/first-recording/pipeline");

    const view = render(
      <RecordingPipelineWorkspace
        recordingId="first-recording"
        stageKey={null}
        compare={false}
      />,
    );
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        "/recordings/first-recording/pipeline/events",
      ),
    );

    window.history.pushState({}, "", "/recordings/second-recording/pipeline");
    view.rerender(
      <RecordingPipelineWorkspace
        recordingId="second-recording"
        stageKey={null}
        compare={false}
      />,
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/recordings/second-recording/pipeline?stage=events",
        expect.anything(),
      ),
    );
    expect(window.location.pathname).toBe(
      "/recordings/second-recording/pipeline",
    );

    resolveSecond(
      new Response(JSON.stringify(workspaceFor("second-recording", true)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        "/recordings/second-recording/pipeline/table_observations",
      ),
    );
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
      within(inspector).getByRole("button", { name: "Detect events…" }),
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
});
