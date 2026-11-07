import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PipelineWorkspaceStage } from "../api/client";
import { normalizeWorkspaceSelectionFixture } from "../test/normalizeWorkspaceSelectionFixture";
import { parseSearchLimits } from "./RoundAnalysisFormatting";
import {
  ObservationRunControls,
  RoundAnalysisControls,
} from "./ObservationAndAnalysisControls";
import { analysisPath } from "./roundAnalysisUrl";

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
    compatible_input_sets: [],
    selection_revision: null,
    selected_generated: null,
    selected_completed_reference: null,
    runs: [],
    analyses: [],
    can_run: true,
    run_blockers: [],
    comparable_run_ids: [],
    ...normalizeWorkspaceSelectionFixture(overrides),
  } as PipelineWorkspaceStage;
}

const job = {
  id: "accepted-job-1",
  label: "Accepted fixture job",
  type: "fixture",
  state: "queued",
  parent_id: null,
  schema_version: "backend-job/v1",
  capabilities: {
    cancel: { allowed: true },
    retry: { allowed: false },
    reorder: { allowed: false },
  },
  context: {},
  correlation_id: null,
  coverage: null,
  created_at: "2026-11-07T00:00:00Z",
  creator: null,
  failure: null,
  finished_at: null,
  idempotency_key: "key",
  implementation: {},
  inputs: [],
  phase: "queued",
  request: {},
  request_hash: "hash",
  results: [],
  retry_of: null,
  revision: 1,
  started_at: null,
  steps: [],
  updated_at: "2026-11-07T00:00:00Z",
  waiting_reason: null,
  warnings: [],
  worker_owner: null,
};

function stubJobAcceptance() {
  const fetchMock = vi.fn<typeof fetch>((_input, init) =>
    Promise.resolve(
      new Response(JSON.stringify(job), {
        status: init?.method === "POST" ? 202 : 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("observation and round-analysis launch modals", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("submits all exact event, visible-card, and identity revisions through one accepted job", async () => {
    const fetchMock = stubJobAcceptance();
    const refs = ["events", "visible_cards", "visual_identities"].map(
      (role) => ({
        node_id: `node-${role}`,
        revision_id: `revision-${role}`,
        revision_policy: "historical",
      }),
    );
    const observations = stage("table_observations", {
      compatible_input_sets: [
        { input_node_refs: refs, display_label: "Exact generated set" },
      ],
    });
    render(
      <ObservationRunControls
        recordingId="recording-1"
        stage={observations}
        stages={[observations]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Assemble table observations…" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(/node-events@revision-events/),
    ).toBeVisible();
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "Start assemble table observations",
      }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const [url, init] = fetchMock.mock.calls.find(
      ([, request]) => request?.method === "POST",
    )!;
    expect(url).toBe("/api/jobs");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
    expect(JSON.parse(String(init?.body))).toMatchObject({
      type: "table_observation_assembly",
      context: { recording_id: "recording-1" },
      request: { input_node_refs: refs },
    });
    expect(
      await screen.findByRole("link", { name: "accepted-job-1" }),
    ).toHaveAttribute("href", "/jobs/accepted-job-1");
  });

  it("keeps the observation action visible and blocks an incomplete role set", async () => {
    stubJobAcceptance();
    const observations = stage("table_observations", {
      compatible_input_sets: [
        {
          input_node_refs: [
            {
              node_id: "events",
              revision_id: "only-events",
              revision_policy: "historical",
            },
          ],
          display_label: "Incomplete set",
        },
      ],
    });
    render(
      <ObservationRunControls
        recordingId="recording-1"
        stage={observations}
        stages={[observations]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble table observations…" }),
    );
    expect(
      screen.getByText(
        /Select a compatible event, visible-card, and visual-identity revision set/,
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Start assemble table observations" }),
    ).toBeDisabled();
  });

  it("requires an explicit choice when several compatible role sets exist", async () => {
    stubJobAcceptance();
    const makeRefs = (suffix: string) =>
      ["events", "visible_cards", "visual_identities"].map((role) => ({
        node_id: `node-${role}-${suffix}`,
        revision_id: `revision-${role}-${suffix}`,
        revision_policy: "historical",
      }));
    const observations = stage("table_observations", {
      compatible_input_sets: [
        { input_node_refs: makeRefs("a"), display_label: "Branch A" },
        { input_node_refs: makeRefs("b"), display_label: "Branch B" },
      ],
    });
    render(
      <ObservationRunControls
        recordingId="recording-1"
        stage={observations}
        stages={[observations]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble table observations…" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Compatible input set")).toHaveValue(
      "",
    );
    expect(
      within(dialog).getByRole("button", {
        name: "Start assemble table observations",
      }),
    ).toBeDisabled();
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Compatible input set"),
      JSON.stringify(makeRefs("b")),
    );
    expect(
      within(dialog).getByRole("button", {
        name: "Start assemble table observations",
      }),
    ).toBeEnabled();
  });

  it("retries uncertain observation acceptance with the same frozen request and key", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(job), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const refs = ["events", "visible_cards", "visual_identities"].map(
      (role) => ({
        node_id: `node-${role}`,
        revision_id: `revision-${role}`,
        revision_policy: "historical",
      }),
    );
    const observations = stage("table_observations", {
      compatible_input_sets: [
        { input_node_refs: refs, display_label: "Exact set" },
      ],
    });
    render(
      <ObservationRunControls
        recordingId="recording-1"
        stage={observations}
        stages={[observations]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Assemble table observations…" }),
    );
    const dialog = screen.getByRole("dialog");
    const start = within(dialog).getByRole("button", {
      name: "Start assemble table observations",
    });
    await userEvent.click(start);
    expect(
      await within(dialog).findByText(/Acceptance is uncertain/),
    ).toBeVisible();
    expect(
      within(dialog).getByLabelText("Compatible input set"),
    ).toBeDisabled();
    await userEvent.click(start);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const first = fetchMock.mock.calls[0]?.[1];
    const second = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(first?.headers).get("Idempotency-Key")).toBe(
      new Headers(second?.headers).get("Idempotency-Key"),
    );
    expect(first?.body).toBe(second?.body);
  });

  it("blocks missing facts and duplicate players, then submits exact observation and explicit facts", async () => {
    const fetchMock = stubJobAcceptance();
    const observation = stage("round_analyses", {
      input_options: [
        {
          revision_id: "obs-r1",
          node_id: "observations-node",
          node_revision_id: "observations-node-r1",
          content_type: "table_observations",
          origin: "processor",
          completion_state: "complete",
          coverage_state: "assembled-events",
          display_label: "Observation output",
          content_sha256: "a".repeat(64),
          input_revision_ids: [],
          producer: {},
          coverage: {},
          created_at: "2026-11-07T00:00:00Z",
        },
      ],
    });
    render(
      <RoundAnalysisControls
        recordingId="recording-1"
        stage={observation}
        selectedAnalysisId={null}
        onRefresh={async () => undefined}
        onSelectAnalysis={() => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Reconstruct one round…" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Enter the game ID.")).toBeVisible();
    expect(within(dialog).getByText("Enter the round ID.")).toBeVisible();
    expect(
      within(dialog).getByRole("button", {
        name: "Start reconstruct one round",
      }),
    ).toBeDisabled();

    const fill = async (name: string, value: string) =>
      userEvent.type(within(dialog).getByLabelText(name), value);
    await fill("Game ID", "game-1");
    await fill("Round ID", "round-1");
    await fill("Session ID", "session-1");
    await fill("Four active players in seat order", "north, east, north, west");
    await fill("Dealer player ID", "east");
    await fill("First-trick leader", "west");
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Rules version"),
      "v1",
    );
    expect(
      within(dialog).getByText("The four active player IDs must be distinct."),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("button", {
        name: "Start reconstruct one round",
      }),
    ).toBeDisabled();

    const players = within(dialog).getByLabelText(
      "Four active players in seat order",
    );
    await userEvent.clear(players);
    await userEvent.type(players, "north, east, south, west");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "Start reconstruct one round",
      }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(
      ([, request]) => request?.method === "POST",
    )!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      type: "round_analysis",
      context: { recording_id: "recording-1" },
      request: {
        recording_id: "recording-1",
        table_observation_node_ref: {
          node_id: "observations-node",
          revision_id: "observations-node-r1",
        },
        round_context: {
          game_id: "game-1",
          round_id: "round-1",
          active_players: ["north", "east", "south", "west"],
          dealer: "east",
          first_trick_leader: "west",
        },
        rules_version: "v1",
        search: {
          max_missing_plays: 1,
          max_hypotheses: 256,
          max_search_nodes: 250000,
        },
      },
    });
    expect(
      await screen.findByRole("link", { name: "accepted-job-1" }),
    ).toHaveAttribute("href", "/jobs/accepted-job-1");
  });

  it("parses bounded search limits and encodes analysis routes", () => {
    expect(parseSearchLimits("0", "10", "100")).toEqual({
      max_missing_plays: 0,
      max_hypotheses: 10,
      max_search_nodes: 100,
    });
    expect(parseSearchLimits("-1", "10", "100")).toBeNull();
    expect(analysisPath("recording-1", "analysis/1")).toBe(
      "/recordings/recording-1/pipeline/round_analyses?analysis=analysis%2F1",
    );
  });
});
