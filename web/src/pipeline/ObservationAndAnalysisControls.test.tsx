import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";

import type { PipelineWorkspaceStage } from "../api/client";
import {
  ObservationRunControls,
  RoundAnalysisControls,
} from "./ObservationAndAnalysisControls";

function stage(
  key: PipelineWorkspaceStage["key"],
  overrides: Record<string, unknown> = {},
): PipelineWorkspaceStage {
  return {
    key,
    processor_key: key,
    processor_type: key,
    output_content_type: key,
    has_maintained_reference: key !== "round_analyses",
    state: "empty",
    input_options: [],
    compatible_input_sets: [],
    selection_revision: null,
    selected_generated_revision_id: null,
    selected_completed_reference_revision_id: null,
    runs: [],
    analyses: [],
    reference: null,
    can_run: true,
    run_blockers: [],
    can_review: false,
    review_blockers: [],
    comparable_run_ids: [],
    ...overrides,
  } as PipelineWorkspaceStage;
}

function runResponse(status = "complete") {
  return {
    run_id: "observation-run-1",
    recording_id: "recording-controls",
    processor_type: "observation-assembly",
    status,
    attempt: 1,
    request: {
      run_id: "observation-run-1",
      input_revision_ids: ["events-1", "visible-1", "identity-1"],
      implementation: { name: "observation-assembler", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
    },
    state: {
      status,
      progress: { completed: 1, total: 1 },
      terminal_failure: null,
    },
  };
}

describe("observation and analysis controls", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits only the backend-approved exact revision set", async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse()), {
          status: init?.method === "POST" ? 202 : 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-1",
    });
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-1",
    });
    const identities = stage("visual_identities", {
      selected_generated_revision_id: "identity-1",
    });
    const observations = stage("table_observations", {
      compatible_input_sets: [
        {
          input_revision_ids: ["events-1", "visible-1", "identity-1"],
          display_label:
            "Generated events + generated cards + generated identities",
        },
      ],
    });

    render(
      <ObservationRunControls
        recordingId="recording-controls"
        stage={observations}
        stages={[events, visible, identities, observations]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Assemble observations" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST"),
      ).toBeDefined(),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      request: {
        input_revision_ids: ["events-1", "visible-1", "identity-1"],
        implementation: { name: "observation-assembler", version: "v1" },
      },
    });
  });

  it("requires explicit round context and sends pipeline analysis inputs", async () => {
    const analysisStatus = {
      analysis_id: "550e8400-e29b-41d4-a716-446655440033",
      recording_id: "recording-controls",
      round_id: "round-1",
      session_id: "550e8400-e29b-41d4-a716-446655440034",
      state: "complete",
      total_evidence_packages: 0,
      completed_evidence_packages: 0,
      result: null,
      error: null,
      created_at: "2026-09-06T00:00:00Z",
      started_at: "2026-09-06T00:00:00Z",
      completed_at: "2026-09-06T00:00:01Z",
    };
    const recording = {
      recording_id: "recording-controls",
      session_id: "550e8400-e29b-41d4-a716-446655440034",
      round_id: "round-1",
      source: {
        game_id: "game-1",
        round_id: "round-1",
      },
    };
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = String(input);
      const body =
        path === "/v1/recordings/recording-controls"
          ? recording
          : analysisStatus;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: init?.method === "POST" ? 202 : 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const observation = stage("table_observations", {
      input_options: [
        {
          revision_id: "observations-1",
          content_type: "table_observations",
          origin: "processor",
          completion_state: "complete",
          coverage_state: "assembled-events",
          display_label: "Generated observations",
          content_sha256: "a".repeat(64),
          input_revision_ids: ["events-1", "visible-1", "identity-1"],
          producer: {},
          coverage: {},
          created_at: "2026-09-06T00:00:00Z",
        },
      ],
      selected_generated_revision_id: "observations-1",
    });
    const analyses = stage("round_analyses", {
      can_run: true,
      input_options: [],
    });
    const onSelectAnalysis = vi.fn();

    render(
      <RoundAnalysisControls
        recordingId="recording-controls"
        stage={{ ...analyses, input_options: observation.input_options }}
        selectedAnalysisId={null}
        onRefresh={async () => undefined}
        onSelectAnalysis={onSelectAnalysis}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Start reconstruction" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST"),
      ).toBeDefined(),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      table_observation_revision_id: "observations-1",
      round_context: {
        game_id: "game-1",
        round_id: "round-1",
        active_players: ["seat-1", "seat-2", "seat-3", "seat-4"],
      },
      rules_version: "v1",
    });
    expect(onSelectAnalysis).toHaveBeenCalledWith(
      "550e8400-e29b-41d4-a716-446655440033",
    );
  });
});
