import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AutomatedPipelineRun,
  PipelineWorkspace,
} from "../api/pipelineContracts";
import { AutomatedPipelineControls } from "./AutomatedPipelineControls";

const workspace = {
  recording_id: "recording-1",
  video: {
    recording_id: "recording-1",
    relative_path: "video.mp4",
    duration_us: 1,
    byte_length: 1,
    video_sha256: "a".repeat(64),
  },
  stages: [
    "events",
    "visible_cards",
    "visual_identities",
    "table_observations",
    "round_analyses",
  ].map((key) => ({ key, runs: [] })),
} as unknown as PipelineWorkspace;

const run: AutomatedPipelineRun = {
  schema_version: "automated-pipeline-run/v1",
  run_id: "run-1",
  recording_id: "recording-1",
  status: "running",
  failure: null,
  request: {},
  stages: [
    "event_proposals",
    "visible_card_and_pile_proposals",
    "card_scene_and_calibration",
    "visual_identity_proposals",
    "table_observations",
    "reconstruction",
  ].map((name) => ({
    name,
    status: "running",
    run_id: null,
    input_revision_ids: [],
    output_revision_ids: [],
    failure: null,
  })),
};
const completedRun: AutomatedPipelineRun = {
  ...run,
  status: "complete",
  stages: run.stages.map((stage) => ({
    ...stage,
    status: "complete",
    output_revision_ids:
      stage.name === "reconstruction"
        ? ["analysis-1"]
        : [`${stage.name}-revision`],
  })),
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("AutomatedPipelineControls", () => {
  it("starts without round metadata and restores every completed stage and analysis after reload", async () => {
    const fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/v1/recordings/recording-1")) {
          return jsonResponse({
            recording_id: "recording-1",
            session_id: "session-1",
            round_id: "round-1",
            source: { game_id: "game-1", round_id: "round-1" },
            video: { path: "video.mp4" },
          });
        }
        if (url.endsWith("/pipeline/runs") && init?.method === "POST")
          return jsonResponse(run, 202);
        if (url.endsWith("/pipeline/runs/run-1"))
          return jsonResponse(completedRun);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetch);
    const onRefresh = vi.fn(async () => undefined);
    const view = render(
      <AutomatedPipelineControls
        recordingId="recording-1"
        workspace={workspace}
        onRefresh={onRefresh}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start complete pipeline" }),
    );
    expect(
      await screen.findByRole("link", { name: "View job" }),
    ).toHaveAttribute("href", "/jobs/run-1");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/pipeline/runs"),
      expect.objectContaining({ method: "POST" }),
    );
    const startCall = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/pipeline/runs") && init?.method === "POST",
    );
    const startPayload = JSON.parse(String(startCall?.[1]?.body));
    expect(startPayload).toMatchObject({
      stage_requests: {
        visible_card_and_pile_proposals: {
          configuration: { provider: "local-rfdetr-segmentation" },
        },
        visual_identity_proposals: { configuration: { provider: "local" } },
      },
    });
    for (const field of [
      "session_id",
      "game_id",
      "round_id",
      "round_context",
      "dealer",
      "first_trick_leader",
    ])
      expect(startPayload).not.toHaveProperty(field);
    expect(
      screen.queryByLabelText(
        /Game ID|Round ID|Session ID|Dealer|leader|player/i,
      ),
    ).not.toBeInTheDocument();

    view.unmount();
    render(
      <AutomatedPipelineControls
        recordingId="recording-1"
        workspace={workspace}
        onRefresh={onRefresh}
      />,
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/pipeline/runs/run-1"),
        expect.objectContaining({ headers: expect.any(Headers) }),
      ),
    );
    expect(
      await screen.findByRole("link", { name: "View job" }),
    ).toHaveAttribute("href", "/jobs/run-1");
    expect(screen.getAllByRole("link")).toHaveLength(7);
    expect(screen.getByRole("link", { name: "View job" })).toHaveAttribute(
      "href",
      "/jobs/run-1",
    );
    expect(
      screen.getByRole("link", { name: /Event proposals/ }),
    ).toHaveAttribute("href", expect.stringContaining("/pipeline/events"));
    expect(
      screen.getByRole("link", { name: /Round analysis/ }),
    ).toHaveAttribute("href", expect.stringContaining("analysis=analysis-1"));
  });

  it("shows the failed stage and its cause after restoring a run", async () => {
    window.localStorage.setItem("automated-pipeline-run:recording-1", "run-1");
    const failed: AutomatedPipelineRun = {
      ...run,
      status: "failed",
      failure: { message: "Visible-card provider failed." },
      stages: run.stages.map((stage) =>
        stage.name === "visible_card_and_pile_proposals"
          ? {
              ...stage,
              status: "failed",
              failure: { message: "Checkpoint is missing." },
            }
          : stage,
      ),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/v1/recordings/recording-1")) {
          return jsonResponse({
            recording_id: "recording-1",
            session_id: "session-1",
            round_id: "round-1",
            source: {},
            video: { path: "video.mp4" },
          });
        }
        if (url.endsWith("/pipeline/runs/run-1")) return jsonResponse(failed);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(
      <AutomatedPipelineControls
        recordingId="recording-1"
        workspace={workspace}
        onRefresh={async () => undefined}
      />,
    );
    expect(
      await screen.findByText(/Visible-card provider failed/),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("listitem")
        .find((item) => item.textContent?.includes("Checkpoint is missing")),
    ).toBeInTheDocument();
  });
});
