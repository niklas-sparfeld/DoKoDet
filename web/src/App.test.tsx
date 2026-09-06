import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, afterEach, describe, vi } from "vitest";

import { App } from "./App";

const recordingId = "recording-fixture";

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
    has_maintained_reference: key !== "round_analyses",
    state: key === "events" ? "video-only" : "empty",
    input_options: [],
    compatible_input_sets: [],
    selection_revision: key === "round_analyses" ? null : 0,
    selected_generated_revision_id: null,
    selected_completed_reference_revision_id: null,
    runs: [],
    analyses: [],
    reference:
      key === "round_analyses"
        ? null
        : {
            state: "empty",
            draft_revision: null,
            selected_completion: null,
            source_revision_id: null,
            coverage: null,
            coverage_state: "none",
            affected_count: 0,
            updated_at: null,
          },
    can_run: key === "events",
    run_blockers: key === "events" ? [] : ["Waiting for the event revision."],
    can_review: false,
    review_blockers: [],
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

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

  it("renders each recording as a compact row with a random screenshot", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          response({
            recordings: [
              {
                recording_id: recordingId,
                source_asset_id: "source-fixture",
                video_id: "video-fixture",
                session_id: "session-fixture",
                state: "accepted",
                source_sha256: "a".repeat(64),
                received_at: "2026-09-06T12:00:00Z",
                round_id: "round-7",
                evidence_package_ids: [],
                analyses: [],
                can_start_analysis: false,
                analysis_blocker: "The pipeline is not ready.",
              },
            ],
          }),
        ),
      ),
    );

    render(<App />);

    const row = await screen.findByRole("link", { name: "Open round-7" });
    expect(row).toHaveAttribute("href", `/recordings/${recordingId}`);
    expect(
      screen.getByRole("img", { name: "Random screenshot from round-7" }),
    ).toBeInTheDocument();
    expect(row.querySelector("video")).toHaveAttribute(
      "src",
      `/v1/repository-bundles/${recordingId}/video`,
    );
    expect(row.querySelectorAll("button")).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Refresh" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Open pipeline")).not.toBeInTheDocument();
    expect(screen.queryByText("Start reconstruction")).not.toBeInTheDocument();
    expect(screen.queryByText("Analyses")).not.toBeInTheDocument();
  });

  it("enters the recording pipeline without loading retired review routes", async () => {
    window.history.pushState({}, "", `/recordings/${recordingId}`);
    const fetchMock = vi.fn<typeof fetch>((input) => {
      expect(String(input)).toBe(`/api/recordings/${recordingId}/pipeline`);
      return Promise.resolve(response(workspace()));
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
    expect(
      fetchMock.mock.calls.every(([input]) =>
        String(input).startsWith(`/api/recordings/${recordingId}/pipeline`),
      ),
    ).toBe(true);
  });

  it("restores stage and view changes through browser history", async () => {
    window.history.pushState(
      {},
      "",
      `/recordings/${recordingId}/pipeline/events?view=generated`,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(response(workspace()))),
    );

    render(<App />);

    expect(
      await screen.findByRole("region", { name: "Events task surface" }),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Reviewed" }));
    await waitFor(() => expect(window.location.search).toBe("?view=reviewed"));

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
    expect(window.location.search).toBe("?view=reviewed");
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
