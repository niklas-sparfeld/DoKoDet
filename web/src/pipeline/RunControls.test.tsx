import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";

import type { PipelineWorkspaceStage } from "../api/client";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";
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
    state: "empty",
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

function option(revisionId: string, displayLabel = revisionId) {
  return {
    revision_id: revisionId,
    node_id: `node-${revisionId}`,
    node_revision_id: `node-revision-${revisionId}`,
    is_current_head: true,
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

function jobResponse(
  id: string,
  state: "queued" | "running" | "succeeded" | "failed" = "queued",
) {
  return {
    id,
    state,
    request: { processor_request: { run_id: id } },
    steps: [],
    failure: null,
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
          new Response(JSON.stringify(jobResponse("events-job-1")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(jobResponse("events-job-1")), {
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
      screen.getByRole("button", { name: "Detect events…" }),
    );
    expect(screen.getByText("Source: accepted recording video")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect events" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({
          method: "POST",
          headers: expect.any(Headers),
        }),
      ),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(new Headers(postCall?.[1]?.headers).get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/i,
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      type: "event_processing",
      context: { recording_id: "recording-run-controls" },
      request: {
        request: {
          implementation: { name: "cardeventnet", version: "file-v1" },
          configuration: {},
          extraction_policy: { policy_id: "exact-event/v1" },
          crop_policy: null,
        },
      },
    });
    expect(
      screen.getByRole("link", { name: "View job events-job-1" }),
    ).toHaveAttribute("href", "/jobs/events-job-1");
  });

  it("keeps an unavailable event source visible and blocks submission", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events", {
          can_run: false,
          run_blockers: ["The accepted recording video is unavailable."],
        })}
        stages={[stage("events", { can_run: false })]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Detect events…" }),
    );
    expect(
      screen.getByText("The accepted recording video is unavailable."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Start detect events" }),
    ).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
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
      "The request was rejected. Correct the inputs and try again.";
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
      screen.getByRole("button", { name: "Detect events…" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect events" }),
    );

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("explains how to continue when the local identity bundle is obsolete", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: "invalid_pipeline_request",
              message:
                "The local visible-card identity classifier could not start: the configured DINOv3 bundle uses an obsolete uncalibrated smoke format; export a current calibrated 25-class bundle",
              details: [],
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
      input_options: [
        {
          ...option("visible-generated"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
      ],
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

    expect(
      await screen.findByText(
        /Select Cloud to continue, or configure a current Local bundle/,
      ),
    ).toBeInTheDocument();
  });

  it("links the accepted event job to shared job details", async () => {
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
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = String(input);
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(jobResponse("events-job-1", "queued")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      const body =
        path === "/api/jobs/events-job-1"
          ? jobResponse("events-job-1", "succeeded")
          : response;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
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
      screen.getByRole("button", { name: "Detect events…" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect events" }),
    );
    expect(
      await screen.findByRole("link", { name: /View job/ }),
    ).toHaveAttribute("href", "/jobs/events-job-1");
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
        option("events-reviewed", "Reviewed events"),
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
    expect(
      screen.getByText("Reviewed · node-revision-events-reviewed"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByText("Use another retained revision"));
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact input revision" }),
      "node-revision-events-old",
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
        request: {
          input_node_ref: {
            node_id: "node-events-old",
            revision_id: "node-revision-events-old",
            revision_policy: "historical",
          },
        },
      },
    });
  });

  it("starts a visible-card run with the selectable fine-frame refinement provider", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      const body = url.endsWith("/api/jobs")
        ? { id: "visible-run-fine-frame" }
        : url.includes("/api/jobs/")
          ? {
              id: "visible-run-fine-frame",
              state: "running",
              request: {
                processor_request: { processor_type: "visible-card-detection" },
              },
              steps: [],
              failure: null,
            }
          : runResponse("visible-run-fine-frame");
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
      input_options: [option("events-generated")],
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

    const modelSelector = screen.getByRole("combobox", {
      name: "Model variant",
    });
    expect(
      within(modelSelector).getByRole("option", {
        name: "Local · RF-DETR fine-frame refinement",
      }),
    ).toBeInTheDocument();
    await userEvent.selectOptions(modelSelector, "local-rfdetr-fine-frame");
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
      type: "visible_card_detection",
      context: { recording_id: "recording-run-controls" },
      request: {
        request: {
          input_node_ref: {
            node_id: "node-events-generated",
            revision_id: "node-revision-events-generated",
            revision_policy: "current_head",
          },
          configuration: { provider: "local-rfdetr-fine-frame" },
        },
      },
    });
  });

  it("starts a visible-card crop refinement review run", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("visible-run-crop-review")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
      input_options: [option("events-generated")],
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
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Model variant" }),
      "local-rfdetr-crop-review",
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
        request: { configuration: { provider: "local-rfdetr-crop-review" } },
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
      input_options: [
        {
          ...option("visible-generated"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
        {
          ...option("visible-reviewed"),
          content_type: "visible_cards",
          origin: "manual",
          producer: { kind: "human" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["node-revision-visible-generated"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
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

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Crop geometry input" }),
      "reviewed_virtual_card:node-revision-visible-reviewed",
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
        input_node_ref: {
          node_id: "node-visible-reviewed",
          revision_id: "node-revision-visible-reviewed",
          revision_policy: "current_head",
        },
        crop_input_kind: "reviewed_virtual_card",
        crop_policy: {
          policy_id: "oracle_visible_region",
          output_encoding: "ppm",
        },
      },
    });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Crop geometry input" }),
      "gemini_polygon:node-revision-visible-generated",
    );
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
        input_node_ref: {
          node_id: "node-visible-generated",
          revision_id: "node-revision-visible-generated",
          revision_policy: "current_head",
        },
        crop_input_kind: "gemini_polygon",
        configuration: { provider: "gemini" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });

  it("lists exact proposed scene revisions and requires a choice when several exist", async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (String(input).endsWith("/visual-identities/proposed-crop-inputs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              recording_id: "recording-run-controls",
              inputs: [
                {
                  node_id: "proposal-node-one",
                  revision_id: "proposal-one",
                  created_at: "2026-11-03T00:00:00Z",
                  proposal_data_digest: "a".repeat(64),
                  detector_revision_id: "detector-one",
                  calibration_revision_id: "calibration-one",
                  supported_frame_count: 2,
                  unsupported_frame_count: 1,
                },
                {
                  node_id: "proposal-node-two",
                  revision_id: "proposal-two",
                  created_at: "2026-11-04T00:00:00Z",
                  proposal_data_digest: "b".repeat(64),
                  detector_revision_id: "detector-two",
                  calibration_revision_id: "calibration-two",
                  supported_frame_count: 4,
                  unsupported_frame_count: 0,
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(runResponse("identity-proposal")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-proposal")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards");
    const identities = stage("visual_identities");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );

    const selector = screen.getByRole("combobox", {
      name: "Crop geometry input",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /proposal-two/ }),
      ).toBeInTheDocument(),
    );
    expect(selector).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Run processor" }),
    ).toBeDisabled();
    await userEvent.selectOptions(
      selector,
      "proposed_virtual_cards:proposal-two",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Run processor" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]
          ?.body,
      ),
    );
    expect(body).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "proposal-node-two",
          revision_id: "proposal-two",
          revision_policy: "historical",
        },
        crop_input_kind: "proposed_virtual_cards",
        configuration: { provider: "local" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
    expect(body.request.visible_card_revision_id).toBeUndefined();
  });

  it("preselects one crop input and requires an explicit choice when several exist", async () => {
    const oneInput = stage("visible_cards", {
      input_options: [
        {
          ...option("gemini-only"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["gemini-only"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
    });
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const identities = stage("visual_identities");
    const { rerender } = render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[oneInput, identities]}
        onRefresh={async () => undefined}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: "Crop geometry input" }),
    ).toHaveValue("gemini_polygon:node-revision-gemini-only");

    const twoInputs = stage("visible_cards", {
      input_options: [
        ...oneInput.input_options,
        {
          ...option("rfdetr-one"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "rfdetr-run" },
        },
      ],
      runs: [
        ...oneInput.runs,
        {
          run_id: "rfdetr-run",
          output_revision_ids: ["node-revision-rfdetr-one"],
          configuration: { provider: "local-rfdetr-segmentation" },
          request: { configuration: { provider: "local-rfdetr-segmentation" } },
        },
      ],
    });
    rerender(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[twoInputs, identities]}
        onRefresh={async () => undefined}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: "Crop geometry input" }),
    ).toHaveValue("");
    expect(
      screen.getByRole("option", { name: /Generated · RF-DETR/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run processor" }),
    ).toBeDisabled();
    await waitFor(() =>
      expect(
        screen.getByText(/none is selected automatically/i),
      ).toBeInTheDocument(),
    );
  });

  it("uses the local classifier with the generated RF-DETR crop input", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-local")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      input_options: [
        {
          ...option("rfdetr-one"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "rfdetr-run" },
        },
      ],
      runs: [
        {
          run_id: "rfdetr-run",
          output_revision_ids: ["node-revision-rfdetr-one"],
          configuration: { provider: "local-rfdetr-segmentation" },
          request: { configuration: { provider: "local-rfdetr-segmentation" } },
        },
      ],
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
    await userEvent.click(screen.getByRole("button", { name: "Local" }));
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
        input_node_ref: {
          node_id: "node-rfdetr-one",
          revision_id: "node-revision-rfdetr-one",
          revision_policy: "current_head",
        },
        crop_input_kind: "rfdetr_segment",
        configuration: { provider: "local" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });

  it("explains why reviewed virtual-card input is unavailable", () => {
    const visible = stage("visible_cards", {
      input_options: [
        {
          ...option("generated-visible"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["generated-visible"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
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
    expect(
      screen.getByText(
        /Reviewed virtual-card input unavailable: complete a maintained visible-card reference\./,
      ),
    ).toBeInTheDocument();
  });

  it("keeps the exact crop-input lineage visible for a historical run", async () => {
    const identityRun = {
      run_id: "identity-history",
      status: "complete",
      attempt: 1,
      request: {
        crop_input: {
          input_kind: "reviewed_virtual_card",
          source_revision_id: "visible-review-17",
          items: Array.from({ length: 12 }, (_, index) => ({
            card_id: `card-${index}`,
          })),
        },
        crop_policy: { policy_id: "oracle_visible_region" },
      },
      state: {},
      input_revision_ids: ["visible-review-17"],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: {},
      crop_policy: { policy_id: "oracle_visible_region" },
      output_revision_ids: [],
      created_at: "2026-09-25T00:00:00Z",
      started_at: null,
      completed_at: null,
      updated_at: "2026-09-25T00:00:00Z",
      progress: { completed: 12, total: 12 },
      failure: null,
      failed_item_count: 0,
    };
    const identities = stage("visual_identities", { runs: [identityRun] });
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[stage("visible_cards"), identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(screen.getByText("Retained runs and actual inputs"));
    expect(
      screen.getByText(
        "Reviewed virtual cards · source visible-review-17 · 12 crop inputs · policy oracle_visible_region",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer retired RF-DETR cascade variants", () => {
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

    expect(screen.queryByRole("option", { name: /cascade/i })).toBeNull();
  });

  it("keeps legacy failed history without inventing a job link", async () => {
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
    expect(
      within(screen.getByRole("list")).queryByRole("link", {
        name: "View job",
      }),
    ).toBeNull();
  });
});
