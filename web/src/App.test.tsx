import userEvent from "@testing-library/user-event";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, afterEach, describe, vi } from "vitest";

import type { RecordingDetail } from "./api/recordingContracts";
import { App } from "./App";

const recordingId = "recording-fixture";
const listRecording = {
  recording_id: recordingId,
  source_asset_id: "source-fixture",
  video_id: "video-fixture",
  session_id: "session-fixture",
  display_name: "round-7.mov",
  received_at: "2026-09-06T12:00:00Z",
  thumbnail_url: `/v1/repository-bundles/${recordingId}/thumbnail`,
  metadata_state: "available",
  selections: [
    "events",
    "visible_cards",
    "virtual_scenes",
    "card_scene_proposals",
    "visual_identities",
    "table_observations",
  ].map((content_type) => ({
    content_type,
    state:
      content_type === "events" || content_type === "card_scene_proposals"
        ? "selected"
        : "not-selected",
    selected_generated:
      content_type === "events"
        ? { node_id: "event-node", revision_id: "event-revision" }
        : null,
    selected_completed_reference:
      content_type === "card_scene_proposals"
        ? { node_id: "proposal-node", revision_id: "proposal-reference" }
        : null,
  })),
};

function stage(
  key:
    | "events"
    | "visible_cards"
    | "visual_identities"
    | "table_observations"
    | "round_analyses",
  overrides: Record<string, unknown> = {},
) {
  return {
    key,
    processor_key: key,
    processor_type: key,
    output_content_type: key,
    state: key === "events" ? "video-only" : "empty",
    input_options: [],
    compatible_input_sets: [],
    selection_revision: key === "round_analyses" ? null : 0,
    selected_generated: null,
    selected_completed_reference: null,
    runs: [],
    analyses: [],
    can_run: key === "events",
    run_blockers: key === "events" ? [] : ["Waiting for the event revision."],
    comparable_run_ids: [],
    ...overrides,
  };
}

function workspace(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "pipeline-workspace/v1",
    recording_id: recordingId,
    video: {
      schema_version: "recording-video/v1",
      recording_id: recordingId,
      relative_path: "videos/recording.mov",
      video_sha256: "a".repeat(64),
      byte_length: 12,
      duration_us: 10_000_000,
    },
    stages: [
      stage("events"),
      stage("visible_cards"),
      stage("visual_identities"),
      stage("table_observations"),
      stage("round_analyses"),
    ],
    diagnostics: [],
    ...overrides,
  };
}

function recordingDetail(): RecordingDetail {
  return {
    recording_id: recordingId,
    source_asset_id: "source-fixture",
    video_id: "video-fixture",
    session_id: "session-fixture",
    state: "accepted",
    source_sha256: "a".repeat(64),
    received_at: "2026-09-06T12:00:00Z",
    round_id: "round-7",
    source: {
      original_filename: "recording.mov",
      acquisition_method: "ios_upload",
      allowed_uses: ["training"],
      content_type: "video/quicktime",
      game_id: "game-fixture",
      notes: null,
      recording_id: recordingId,
      retention_state: "active",
      round_id: "round-7",
      session_id: "session-fixture",
      source_permission: "training_only",
      table_setup: "four_players",
      video_id: "video-fixture",
    },
    video: {
      url: `/v1/repository-bundles/${recordingId}/video`,
      content_type: "video/quicktime",
      media_facts: null,
    },
    evidence_package_ids: [],
    analyses: [],
    task_enrollments: [],
    can_start_analysis: false,
    analysis_blocker: "The pipeline is not ready.",
  };
}

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function pipelineLineage() {
  return {
    schema_version: "pipeline-lineage-graph/v1",
    nodes: [],
    revisions: [],
    runs: [],
    artifacts: [],
    edges: [],
  };
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the recording catalog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(response({ recordings: [] }))),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recordings" }),
    ).toBeInTheDocument();
  });

  it("renders each recording as a compact row with a cached thumbnail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          response({
            recordings: [listRecording],
          }),
        ),
      ),
    );

    render(<App />);

    const row = await screen.findByRole("link", { name: "Open round-7.mov" });
    expect(row).toHaveAttribute("href", `/recordings/${recordingId}`);
    expect(within(row).getByText("events")).toBeInTheDocument();
    expect(within(row).getByText("Generated selected")).toBeInTheDocument();
    expect(within(row).getByText("Reference selected")).toBeInTheDocument();
    expect(within(row).getByText("visible cards")).toBeInTheDocument();
    expect(within(row).getAllByText("Not selected")).toHaveLength(4);
    expect(row).toHaveTextContent("Received");
    expect(row).toHaveTextContent("Session");
    expect(row).toHaveTextContent("session-fixture");
    expect(
      screen.getByRole("img", { name: "Cached thumbnail from round-7.mov" }),
    ).toBeInTheDocument();
    expect(row.querySelector("img")).toHaveAttribute(
      "src",
      `/v1/repository-bundles/${recordingId}/thumbnail`,
    );
    expect(row.querySelector("video")).not.toBeInTheDocument();
    expect(row.querySelectorAll("button")).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Refresh" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Open pipeline")).not.toBeInTheDocument();
    expect(screen.queryByText("Start reconstruction")).not.toBeInTheDocument();
    expect(screen.queryByText("Analyses")).not.toBeInTheDocument();
  });

  it("shows selection status without pipeline progress", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          response({
            recordings: [listRecording],
          }),
        ),
      ),
    );

    render(<App />);

    const row = await screen.findByRole("link", { name: "Open round-7.mov" });
    expect(screen.getByText("Generated selected")).toBeInTheDocument();
    expect(screen.getAllByText("Reference selected")).toHaveLength(1);
    expect(screen.getAllByText("Not selected")).toHaveLength(4);
    expect(
      within(row).queryByRole("list", { name: "Pipeline progress" }),
    ).toBeNull();
  });

  it("does not poll the recording catalog for lifecycle while a job is active", async () => {
    vi.useFakeTimers();
    const activeRecording = listRecording;
    let recordingReads = 0;
    const fetchMock = vi.fn<typeof fetch>((input) => {
      if (String(input).startsWith("/api/jobs?"))
        return Promise.resolve(
          response({
            items: [],
            next_cursor: null,
            groups: [],
            queue_revision: 0,
          }),
        );
      expect(String(input)).toBe("/v1/recordings");
      recordingReads += 1;
      return Promise.resolve(response({ recordings: [activeRecording] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<App />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(recordingReads).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(recordingReads).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(recordingReads).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("enters the recording pipeline without loading retired review routes", async () => {
    window.history.pushState({}, "", `/recordings/${recordingId}`);
    const pipelinePaths: string[] = [];
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path.startsWith("/api/jobs?"))
        return Promise.resolve(
          response({
            items: [],
            next_cursor: null,
            groups: [],
            queue_revision: 0,
          }),
        );
      pipelinePaths.push(path);
      if (path === `/api/recordings/${recordingId}/pipeline/lineage`)
        return Promise.resolve(response(pipelineLineage()));
      if (path === `/api/recordings/${recordingId}/pipeline?stage=events`)
        return Promise.resolve(response(workspace()));
      if (path === `/v1/recordings/${recordingId}`)
        return Promise.resolve(response(recordingDetail()));
      throw new Error(`Unexpected fetch request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recording pipeline" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        `/recordings/${recordingId}/pipeline/events`,
      ),
    );
    expect(fetchMock).toHaveBeenCalled();
    expect(pipelinePaths).toEqual([
      `/api/recordings/${recordingId}/pipeline/lineage`,
      `/api/recordings/${recordingId}/pipeline?stage=events`,
      `/v1/recordings/${recordingId}`,
    ]);
  });

  it("restores stage changes through browser history", async () => {
    window.history.pushState(
      {},
      "",
      `/recordings/${recordingId}/pipeline/events`,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        const path = String(input);
        if (path.startsWith("/api/jobs?"))
          return Promise.resolve(
            response({
              items: [],
              next_cursor: null,
              groups: [],
              queue_revision: 0,
            }),
          );
        if (path === `/api/recordings/${recordingId}/pipeline/lineage`)
          return Promise.resolve(response(pipelineLineage()));
        if (path.startsWith(`/api/recordings/${recordingId}/pipeline?stage=`))
          return Promise.resolve(response(workspace()));
        if (path === `/v1/recordings/${recordingId}`)
          return Promise.resolve(response(recordingDetail()));
        throw new Error(`Unexpected fetch request: ${path}`);
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("region", { name: "Events task surface" }),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("link", { name: /Visible cards/ }));
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        `/recordings/${recordingId}/pipeline/visible_cards`,
      ),
    );
    expect(
      screen.getByRole("region", { name: "Visible cards task surface" }),
    ).toBeInTheDocument();

    window.history.back();
    await waitFor(() =>
      expect(window.location.pathname).toBe(
        `/recordings/${recordingId}/pipeline/events`,
      ),
    );
    expect(window.location.search).toBe("");
    expect(
      await screen.findByRole("region", { name: "Events task surface" }),
    ).toBeInTheDocument();
  });

  it("shows a loading error instead of a blank page when a recording cannot load", async () => {
    window.history.pushState({}, "", `/recordings/${recordingId}`);
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.reject(new Error("backend unavailable")),
      ),
    );

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The backend could not be reached.",
    );
  });

  it("does not expose batch review pages from the browser router", async () => {
    window.history.pushState({}, "", "/visible-card-reviews/retired-batch");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(response({ recordings: [] }))),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recordings" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/review workspace/i)).not.toBeInTheDocument();
  });
});
