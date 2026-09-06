import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";

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
