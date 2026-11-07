import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AutomatedPipelineRun,
  PipelineWorkspace,
} from "../api/pipelineContracts";
import { JobStateProvider } from "../jobs/JobState";
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

const run = (runId: string, jobId: string): AutomatedPipelineRun => ({
  schema_version: "automated-pipeline-run/v1",
  run_id: runId,
  job_id: jobId,
  recording_id: "recording-1",
  status: "complete",
  failure: null,
  request: {},
  stages: [
    ["event_proposals", [], ["events-r1"]],
    ["visible_card_and_pile_proposals", ["events-r1"], ["cards-r1"]],
    ["card_scene_and_calibration", ["cards-r1"], ["scenes-r1"]],
    ["visual_identity_proposals", ["scenes-r1"], ["identities-r1"]],
    [
      "table_observations",
      ["events-r1", "cards-r1", "identities-r1"],
      ["observations-r1"],
    ],
    ["reconstruction", ["observations-r1"], ["analysis-r1"]],
  ].map(([name, input_revision_ids, output_revision_ids]) => ({
    name: String(name),
    status: "complete" as const,
    run_id: null,
    child_job_id: `child-${String(name)}`,
    input_revision_ids: input_revision_ids as string[],
    output_revision_ids: output_revision_ids as string[],
    failure: null,
  })),
});

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderControls(onRefresh = vi.fn(async () => undefined)) {
  return render(
    <JobStateProvider>
      <AutomatedPipelineControls
        recordingId="recording-1"
        workspace={workspace}
        onRefresh={onRefresh}
      />
    </JobStateProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("AutomatedPipelineControls", () => {
  it("starts fresh runs with the displayed source, facts, stage settings, and shared Jobs links", async () => {
    let count = 0;
    const fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/jobs?scope=active&limit=50"))
          return jsonResponse({
            items: [],
            next_cursor: null,
            groups: [],
            queue_revision: 1,
          });
        if (url.endsWith("/v1/recordings/recording-1"))
          return jsonResponse({
            recording_id: "recording-1",
            session_id: "session-1",
            round_id: "round-1",
            source_sha256: "b".repeat(64),
            source: { game_id: "game-stored" },
            video: { path: "video.mp4", video_sha256: "a".repeat(64) },
          });
        if (url.endsWith("/pipeline/runs") && init?.method === "POST") {
          count += 1;
          return jsonResponse(run(`run-${count}`, `parent-${count}`), 202);
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetch);
    const onRefresh = vi.fn(async () => undefined);
    renderControls(onRefresh);
    fireEvent.click(
      await screen.findByRole("button", { name: "Run complete pipeline…" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Game ID" }), {
      target: { value: "game-1" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Four active player IDs" }),
      { target: { value: "p1, p2, p3, p4" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Dealer ID" }), {
      target: { value: "p1" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "First-trick leader ID" }),
      { target: { value: "p2" } },
    );
    fireEvent.change(
      screen.getAllByRole("textbox", { name: "Configuration JSON" })[1],
      {
        target: {
          value: '{"provider":"local-rfdetr-segmentation","fixture":"kept"}',
        },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start run complete pipeline" }),
    );
    expect(
      await screen.findByRole("link", { name: "View parent job in Jobs" }),
    ).toHaveAttribute("href", "/jobs/parent-1");
    const post = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/pipeline/runs") && init?.method === "POST",
    );
    const payload = JSON.parse(String(post?.[1]?.body));
    expect(payload).toMatchObject({
      session_id: "session-1",
      round_context: {
        game_id: "game-1",
        round_id: "round-1",
        active_players: ["p1", "p2", "p3", "p4"],
        dealer: "p1",
        first_trick_leader: "p2",
      },
      rules_version: "v1",
      search: {
        max_missing_plays: 1,
        max_hypotheses: 256,
        max_search_nodes: 250000,
      },
      stage_requests: {
        visible_card_and_pile_proposals: {
          model: {},
          configuration: {
            provider: "local-rfdetr-segmentation",
            fixture: "kept",
          },
        },
        visual_identity_proposals: {
          model: {},
          configuration: { provider: "local" },
        },
      },
    });
    expect(screen.getAllByText(/inputs events-r1/)).toHaveLength(2);
    expect(screen.getByText(/outputs analysis-r1/)).toBeInTheDocument();
    expect(
      screen.getByText(/child job child-reconstruction/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Run complete pipeline…" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start run complete pipeline" }),
    );
    await waitFor(() => expect(count).toBe(2));
    const posts = fetch.mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith("/pipeline/runs") && init?.method === "POST",
    );
    expect(JSON.parse(String(posts[0]?.[1]?.body)).idempotency_key).not.toBe(
      JSON.parse(String(posts[1]?.[1]?.body)).idempotency_key,
    );
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("keeps entered facts and settings after invalid preflight and starts no job", async () => {
    let posts = 0;
    const fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/jobs?scope=active&limit=50"))
          return jsonResponse({
            items: [],
            next_cursor: null,
            groups: [],
            queue_revision: 1,
          });
        if (url.endsWith("/v1/recordings/recording-1"))
          return jsonResponse({
            recording_id: "recording-1",
            session_id: "session-1",
            round_id: "round-1",
            source_sha256: "a".repeat(64),
            video: { path: "video.mp4" },
          });
        if (url.endsWith("/pipeline/runs") && init?.method === "POST") {
          posts += 1;
          return jsonResponse(
            {
              error: {
                details: [
                  {
                    field: "preflight",
                    message: "Missing accepted source revision.",
                  },
                ],
              },
            },
            422,
          );
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetch);
    const onRefresh = vi.fn(async () => undefined);
    renderControls(onRefresh);
    fireEvent.click(
      await screen.findByRole("button", { name: "Run complete pipeline…" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Game ID" }), {
      target: { value: "game-kept" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Four active player IDs" }),
      { target: { value: "p1, p2, p3, p4" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Dealer ID" }), {
      target: { value: "p1" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "First-trick leader ID" }),
      { target: { value: "p2" } },
    );
    fireEvent.change(
      screen.getAllByRole("textbox", { name: "Configuration JSON" })[1],
      {
        target: {
          value: '{"provider":"local-rfdetr-segmentation","fixture":"kept"}',
        },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start run complete pipeline" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Missing accepted source revision",
    );
    expect(screen.getByRole("textbox", { name: "Game ID" })).toHaveValue(
      "game-kept",
    );
    expect(
      screen.getByRole("textbox", { name: "Four active player IDs" }),
    ).toHaveValue("p1, p2, p3, p4");
    expect(
      screen.getAllByRole("textbox", { name: "Configuration JSON" })[1],
    ).toHaveValue('{"provider":"local-rfdetr-segmentation","fixture":"kept"}');
    expect(posts).toBe(1);
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
