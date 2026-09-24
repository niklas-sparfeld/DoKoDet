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
  state: Record<string, unknown> = {},
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
      ...state,
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

  it("shows processor progress, activity steps, and log messages", () => {
    const activityResponse = runResponse(
      "activity-run-1",
      "running",
      {},
      {
        progress: { completed: 3, total: 123 },
        metrics: {
          schema_version: "processor-run-activity/v1",
          activity: {
            phase: "calibration",
            message: "Calibrating virtual cards",
            step: 1,
            steps: 3,
          },
          logs: [
            {
              at: "2026-09-24T10:00:00Z",
              level: "info",
              message: "Calibrating virtual cards",
            },
          ],
        },
      },
    );
    const activityRun = {
      ...activityResponse,
      input_revision_ids: [],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
      output_revision_ids: [],
      created_at: "2026-09-24T10:00:00Z",
      started_at: "2026-09-24T10:00:00Z",
      completed_at: null,
      updated_at: "2026-09-24T10:00:00Z",
      progress: { completed: 3, total: 123 },
      failure: null,
      failed_item_count: 0,
    } as unknown as PipelineWorkspaceStage["runs"][number];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(activityRun), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events", { runs: [activityRun] })}
        stages={[stage("events", { runs: [activityRun] })]}
        onRefresh={async () => undefined}
      />,
    );

    expect(screen.getByText("Progress: 3 / 123 items")).toBeInTheDocument();
    expect(
      screen.getByText("Calibrating virtual cards (step 1/3)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Processor log (1 messages)")).toBeInTheDocument();
  });

  it("shows the checkpoint configuration error when a run cannot start", async () => {
    const message =
      "The CardEventNet checkpoint is not configured. Set CARD_EVENT_CHECKPOINT_PATH.";
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: "invalid_pipeline_request",
              message,
              details: [],
            },
          }),
          {
            status: 422,
            headers: { "Content-Type": "application/json" },
          },
        ),
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

  it("opens the stored CardEventNet probability chart", async () => {
    const response = runResponse(
      "events-run-1",
      "complete",
      {},
      {
        metrics: {
          schema_version: "cardeventnet-metrics/v1",
          threshold: 0.5,
          probabilities: [
            { time_s: 0, probability: 0.1 },
            { time_s: 0.5, probability: 0.95 },
            { time_s: 1, probability: 0.2 },
          ],
          events: [{ time_s: 0.5, probability: 0.95 }],
        },
      },
    );
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
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
    await userEvent.click(
      await screen.findByRole("button", { name: "Show probabilities" }),
    );

    expect(
      screen.getByRole("dialog", { name: "CardEventNet probabilities" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "CardEventNet probability over time chart",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img").querySelector("polyline")).toHaveAttribute(
      "points",
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Close probabilities" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "CardEventNet probabilities" }),
    ).not.toBeInTheDocument();
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
        configuration: { provider: "gemini" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });

  it("selects an explicit visible-card model variant", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("visible-local-run")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
    });
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
    });

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Model variant" })).toHaveValue(
      "gemini",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Model variant" }),
      "local-rfdetr-cascade-0070",
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
        configuration: { provider: "local-rfdetr-cascade-0070" },
      },
    });
  });

  it("offers the reviewed and synthetic cascade variants", () => {
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
    });
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
    });

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    expect(screen.getByRole("option", { name: /0068 reviewed/ })).toHaveValue(
      "local-rfdetr-cascade-0068",
    );
    expect(screen.getByRole("option", { name: /0070 synthetic/ })).toHaveValue(
      "local-rfdetr-cascade-0070",
    );
  });

  it("does not inherit the previous visible-card provider when a variant changes", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("visible-cascade-run")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
    });
    const previousRun = {
      ...runResponse("visible-segmentation-run", "complete", {
        configuration: { provider: "local-rfdetr-segmentation" },
      }),
      input_revision_ids: ["events-generated"],
      implementation: { name: "visible-card-detector-adapter", version: "v1" },
      model: { name: "local-rfdetr-segmentation", version: "v1" },
      configuration: { provider: "local-rfdetr-segmentation" },
      output_revision_ids: ["visible-segmentation-revision"],
    } as unknown as PipelineWorkspaceStage["runs"][number];
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
      runs: [previousRun],
    });

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Model variant" }),
      "local-rfdetr-cascade-0068",
    );
    await userEvent.click(screen.getByRole("button", { name: "Run again" }));

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
        configuration: { provider: "local-rfdetr-cascade-0068" },
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
