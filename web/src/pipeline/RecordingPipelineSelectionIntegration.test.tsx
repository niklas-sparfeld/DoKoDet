import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { PIPELINE_STAGE_KEYS } from "./RecordingPipelineWorkspace";
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

describe("recording pipeline selection", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
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
