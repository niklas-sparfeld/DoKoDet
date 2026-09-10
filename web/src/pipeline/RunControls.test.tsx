import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";

import type { PipelineWorkspaceStage } from "../api/client";
import { RunControls } from "./RunControls";

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

function option(revisionId: string, displayLabel = revisionId) {
  return {
    revision_id: revisionId,
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

function runResponse(
  runId: string,
  status = "running",
  request: Record<string, unknown> = {},
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
    },
  };
}

describe("RunControls", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts event detection from the accepted video with a complete frozen request", async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(runResponse("events-run-1")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(runResponse("events-run-1")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events")}
        stages={[stage("events")]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/recordings/recording-run-controls/pipeline/events",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      request: {
        input_revision_ids: [],
        implementation: { name: "cardeventnet", version: "file-v1" },
        configuration: {},
        extraction_policy: { policy_id: "exact-event/v1" },
        crop_policy: null,
      },
    });
    expect(
      screen.getAllByText("Accepted recording video").length,
    ).toBeGreaterThan(0);
  });

  it("shows the checkpoint configuration error when a run cannot start", async () => {
    const message =
      "The CardEventNet checkpoint is not configured. Set CARD_EVENT_CHECKPOINT_PATH.";
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: { message } }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events")}
        stages={[stage("events")]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
    );

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("defaults to reviewed upstream input and permits an exact historical revision", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("visible-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
      selected_completed_reference_revision_id: "events-reviewed",
      input_options: [
        option("events-generated", "Generated events"),
        option("events-old", "Older events"),
      ],
    });
    const visible = stage("visible_cards");

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    expect(screen.getByRole("button", { name: "Reviewed" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Reviewed · events-reviewed")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Use another retained revision"));
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact input revision" }),
      "events-old",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
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
        input_revision_ids: ["events-old"],
        event_revision_id: "events-old",
      },
    });
  });

  it("uses polygon crop policies for visual identity runs", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
      selected_completed_reference_revision_id: "visible-reviewed",
    });
    const identities = stage("visual_identities");

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
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
        visible_card_revision_id: "visible-reviewed",
        crop_policy: {
          policy_id: "oracle_visible_region",
          output_encoding: "ppm",
        },
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Generated" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toHaveLength(2),
    );
    const postCalls = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCalls[1]?.[1]?.body))).toMatchObject({
      request: {
        visible_card_revision_id: "visible-generated",
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });

  it("keeps retry on the same run and explains partial and failed outcomes", async () => {
    const retainedRun = {
      run_id: "failed-run",
      status: "failed" as const,
      attempt: 1,
      request: {
        run_id: "failed-run",
        input_revision_ids: [],
        implementation: { name: "fixture", version: "v1" },
        model: null,
        configuration: {},
        extraction_policy: { policy_id: "exact-event/v1" },
        crop_policy: null,
      },
      state: {},
      input_revision_ids: [],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
      output_revision_ids: [],
      created_at: "2026-09-06T00:00:00Z",
      started_at: "2026-09-06T00:00:00Z",
      completed_at: "2026-09-06T00:00:01Z",
      updated_at: "2026-09-06T00:00:01Z",
      progress: { completed: 1, total: 2 },
      failure: { code: "provider_failed", message: "fixture failed" },
      failed_item_count: 0,
    };
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(runResponse("failed-run")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(runResponse("failed-run", "partial")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events", { runs: [retainedRun] })}
        stages={[stage("events", { runs: [retainedRun] })]}
        onRefresh={async () => undefined}
      />,
    );

    const history = screen.getByText("Retained runs and actual inputs");
    await userEvent.click(history);
    await userEvent.click(
      within(screen.getByRole("list")).getByRole("button", {
        name: "Retry same run",
      }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/recordings/recording-run-controls/pipeline/events/failed-run/retry",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText(/partial result/i)).toBeInTheDocument();
    expect(
      screen.getByText(/retry the same frozen request/i),
    ).toBeInTheDocument();
  });
});
