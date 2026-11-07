import { afterEach, describe, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";
import {
  jobResponse,
  option,
  runResponse,
  stage,
} from "./runControlsTestFixtures";
import type { PipelineWorkspaceStage } from "../api/pipelineContracts";
import { RunControls } from "./RunControls";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RunControls event and visible-card launches", () => {
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
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );

    expect(
      await within(screen.getByRole("dialog")).findByText(
        /configured DINOv3 bundle uses an obsolete uncalibrated smoke format/,
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
  it("submits the exact event revision selected in the visible-card modal", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(jobResponse("visible-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events = stage("events", {
      input_options: [
        option("events-generated", "Generated events"),
        option("events-reviewed", "Reviewed events"),
        option("events-old", "Older events"),
      ],
    });
    const visible = stage("visible_cards", {
      can_run: false,
      run_blockers: ["Select a complete events revision first."],
    });

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact event revision" }),
      "node-revision-events-old",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect visible cards" }),
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
    expect(
      await screen.findByRole("link", { name: /View job visible-run-1/ }),
    ).toHaveAttribute("href", "/jobs/visible-run-1");
  });
  it("keeps visible-card launch available and blocks missing or incompatible inputs", async () => {
    const visible = stage("visible_cards", {
      can_run: false,
      run_blockers: [
        "The selected calibration is incompatible with this input.",
      ],
    });
    const events = stage("events");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    const action = screen.getByRole("button", {
      name: "Detect visible cards…",
    });
    expect(action).toBeInTheDocument();
    await userEvent.click(action);
    expect(
      screen.getByRole("combobox", { name: "Exact event revision" }),
    ).toHaveValue("");
    expect(
      screen.getByText("No compatible event revision is available."),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "The selected calibration is incompatible with this input.",
      ),
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Start detect visible cards" }),
    ).toBeDisabled();
  });
  it("starts visible-card processing with the selected detector and model", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(jobResponse("visible-run-fine-frame")), {
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

    await userEvent.click(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    );
    const modelSelector = screen.getByRole("combobox", {
      name: "Detector and model",
    });
    expect(
      within(modelSelector).getByRole("option", {
        name: "Local · RF-DETR fine-frame refinement",
      }),
    ).toBeInTheDocument();
    await userEvent.selectOptions(modelSelector, "local-rfdetr-fine-frame");
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect visible cards" }),
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
  it("starts visible-card crop refinement from the shared modal", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(jobResponse("visible-run-crop-review")), {
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
    await userEvent.click(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Detector and model" }),
      "local-rfdetr-crop-review",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start detect visible cards" }),
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
});
